# Copyright 2018 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Unit tests for the :mod:`openqml` :class:`QNode` class.
"""
import pytest

import autograd
from autograd import numpy as np

from conftest import BaseTest

import openqml as qm
from openqml.qnode import _flatten
from openqml.plugins.default import CNOT, frx, fry, frz, I, Y, Z
from openqml.device import QuantumFunctionError, DeviceError


def expZ(state):
    return np.abs(state[0]) ** 2 - np.abs(state[1]) ** 2


thetas = np.linspace(-2*np.pi, 2*np.pi, 7)


class TestBasic(BaseTest):
    """Qnode tests.
    """
    def test_qnode_fail(self, qubit_dev1, qubit_dev2, tol):
        "Tests that expected failures correctly raise exceptions."
        par = 0.5

        #---------------------------------------------------------
        ## faulty quantum functions

        # qfunc must return only Expectations
        @qm.qfunc(qubit_dev2)
        def qf(x):
            qm.RX(x, [0])
            return qm.expectation.PauliZ(0), 0.3
        with pytest.raises(QuantumFunctionError, message='must return either'):
            qf(par)

        # all EVs must be returned...
        @qm.qfunc(qubit_dev2)
        def qf(x):
            qm.RX(x, [0])
            ex = qm.expectation.PauliZ(1)
            return qm.expectation.PauliZ(0)
        with pytest.raises(QuantumFunctionError, message='All measured expectation values'):
            qf(par)

        # ...in the correct order
        @qm.qfunc(qubit_dev2)
        def qf(x):
            qm.RX(x, [0])
            ex = qm.expectation.PauliZ(1)
            return qm.expectation.PauliZ(0), ex
        with pytest.raises(QuantumFunctionError, message='All measured expectation values'):
            qf(par)

        # gates must precede EVs
        @qm.qfunc(qubit_dev2)
        def qf(x):
            qm.RX(x, [0])
            ev = qm.expectation.PauliZ(1)
            qm.RY(0.5, [0])
            return ev
        with pytest.raises(QuantumFunctionError, message='gates must precede'):
            qf(par)

        # a wire cannot be measured more than once
        @qm.qfunc(qubit_dev2)
        def qf(x):
            qm.RX(x, [0])
            qm.CNOT([0, 1])
            return qm.expectation.PauliZ(0), qm.expectation.PauliZ(1), qm.expectation.PauliX(0)
        with pytest.raises(QuantumFunctionError, message='can only be measured once'):
            qf(par)

        # device must have enough wires for the qfunc
        @qm.qfunc(qubit_dev2)
        def qf(x):
            qm.RX(x, [0])
            qm.CNOT([0, 2])
            return qm.expectation.PauliZ(0)
        with pytest.raises(QuantumFunctionError, message='device only has'):
            qf(par)

        # CV and discrete ops must not be mixed
        @qm.qfunc(qubit_dev1)
        def qf(x):
            qm.RX(x, [0])
            qm.Displacement(0.5, 0, [0])
            return qm.expectation.PauliZ(0)
        with pytest.raises(QuantumFunctionError, message='Continuous and discrete'):
            qf(par)

        # default plugin cannot execute CV operations, neither gates...
        @qm.qfunc(qubit_dev1)
        def qf(x):
            qm.Displacement(0.5, 0, [0])
            return qm.expectation.X(0)
        with pytest.raises(DeviceError, message='Gate [a-zA-Z]+ not supported on device'):
            qf(par)

        # ...nor observables
        @qm.qfunc(qubit_dev1)
        def qf(x):
            return qm.expectation.X(0)
        with pytest.raises(DeviceError, message='Observable [a-zA-Z]+ not supported on device'):
            qf(par)

        #---------------------------------------------------------
        ## gradient issues

        # undifferentiable operation
        def qf(x):
            qm.BasisState(x, [0,1])
            qm.RX(x, [0])
            return qm.expectation.PauliZ(0)
        q = qm.QNode(qf, qubit_dev2)
        with pytest.raises(ValueError, message='Cannot differentiate wrt'):
            q.gradient(par)

        # operation that does not support the 'A' method
        def qf(x):
            qm.RX(x, [0])
            return qm.expectation.Hermitian(np.diag([x, 0]), 0)
        q = qm.QNode(qf, qubit_dev2)
        with pytest.raises(ValueError, message='analytic gradient method cannot be used with'):
            q.gradient(par, method='A')

        #---------------------------------------------------------
        ## bad input parameters
        def qf_ok(x):
            qm.Rot(0.3, x, -0.2, [0])
            return qm.expectation.PauliZ(0)

        # if indices wrt. which the gradient is taken are specified they must be unique
        q = qm.QNode(qf_ok, qubit_dev2)
        with pytest.raises(ValueError, message='indices must be unique'):
            q.gradient(par, which=[0,0])

        # gradient wrt. nonexistent parameters
        q = qm.QNode(qf_ok, qubit_dev2)
        with pytest.raises(ValueError, message='Tried to compute the gradient wrt'):
            q.gradient(par, which=[0,6])
        with pytest.raises(ValueError, message='Tried to compute the gradient wrt'):
            q.gradient(par, which=[1,-1])

        # unknown grad method
        q = qm.QNode(qf_ok, qubit_dev1)
        with pytest.raises(ValueError, message='Unknown gradient method'):
            q.gradient(par, method='unknown')

        # only order-1 and order-2 finite diff methods are available
        q = qm.QNode(qf_ok, qubit_dev1)
        with pytest.raises(ValueError, message='Order must be 1 or 2'):
            q.gradient(par, method='F', order=3)


    def test_qnode_cv_gradient_methods(self, qubit_dev1, qubit_dev2, tol):
        "Tests the gradient computation methods on CV circuits."
        # we can only use the 'A' method on parameters which only affect gaussian operations that are not succeeded by nongaussian operations

        par = [0.4, -2.3]
        def check_methods(qf, d):
            q = qm.QNode(qf, qubit_dev2)
            q.construct(par)  # NOTE: the default plugin is a discrete (qubit) simulator, it cannot execute CV gates, but the QNode can be constructed
            #print(q.grad_method_for_par)
            self.assertTrue(q.grad_method_for_par == d)

        def qf(x, y):
            qm.Displacement(x, 0, [0])
            qm.CubicPhase(0.2, [0])
            qm.Squeezing(0.3, y, [1])
            qm.Rotation(1.3, [1])
            #qm.Kerr(0.4, [0])  # nongaussian succeeding x but not y   TODO when QNode uses a DAG to describe the circuit, uncomment this line
            return qm.expectation.X(0), qm.expectation.X(1)
        check_methods(qf, {0:'F', 1:'A'})

        def qf(x, y):
            qm.Displacement(x, 0, [0])
            qm.CubicPhase(0.2, [0])  # nongaussian succeeding x
            qm.Squeezing(0.3, x, [1])  # x affects gates on both wires, y unused
            qm.Rotation(1.3, [1])
            return qm.expectation.X(0), qm.expectation.X(1)
        check_methods(qf, {0:'F'})

        def qf(x, y):
            qm.Displacement(x, 0, [0])
            qm.Displacement(1.2, y, [0])
            qm.Beamsplitter(0.2, 1.7, [0, 1])
            qm.Rotation(1.9, [0])
            qm.Kerr(0.3, [1])  # nongaussian succeeding both x and y due to the beamsplitter
            return qm.expectation.X(0), qm.expectation.X(1)
        check_methods(qf, {0:'F', 1:'F'})

        def qf(x, y):
            qm.Kerr(y, [1])
            qm.Displacement(x, 0, [0])
            qm.Beamsplitter(0.2, 1.7, [0, 1])
            return qm.expectation.X(0), qm.expectation.X(1)
        check_methods(qf, {0:'A', 1:'F'})


    def test_qnode_multiple_gate_parameters(self, qubit_dev1, qubit_dev2, tol):
        "Tests that gates with multiple free parameters yield correct gradients."
        par = [0.5, 0.3, -0.7]

        def qf(x, y, z):
            qm.RX(0.4, [0])
            qm.Rot(x, y, z, [0])
            qm.RY(-0.2, [0])
            return qm.expectation.PauliZ(0)

        q = qm.QNode(qf, qubit_dev1)
        value = q(*par)
        grad_A = q.gradient(par, method='A')
        grad_F = q.gradient(par, method='F')

        # analytic method works for every parameter
        self.assertTrue(q.grad_method_for_par == {0:'A', 1:'A', 2:'A'})
        # gradient has the correct length and every element is nonzero
        self.assertEqual(len(grad_A), 3)
        self.assertEqual(np.count_nonzero(grad_A), 3)
        # the different methods agree
        self.assertAllAlmostEqual(grad_A, grad_F, delta=tol)


    def test_qnode_repeated_gate_parameters(self, qubit_dev1, qubit_dev2, tol):
        "Tests that repeated use of a free parameter in a multi-parameter gate yield correct gradients."
        par = [0.8, 1.3]

        def qf(x, y):
            qm.RX(np.pi/4, [0])
            qm.Rot(y, x, 2*x, [0])
            return qm.expectation.PauliX(0)

        q = qm.QNode(qf, qubit_dev1)
        grad_A = q.gradient(par, method='A')
        grad_F = q.gradient(par, method='F')

        # the different methods agree
        self.assertAllAlmostEqual(grad_A, grad_F, delta=tol)


    def test_qnode_parameters_inside_array(self, qubit_dev1, qubit_dev2, tol):
        "Tests that free parameters inside an array passed to an Operation yield correct gradients."
        par = [0.8, 1.3]

        def qf(x, y):
            qm.RX(x, [0])
            qm.RY(x, [0])
            return qm.expectation.Hermitian(np.diag([y, 1]), 0)

        q = qm.QNode(qf, qubit_dev1)
        grad = q.gradient(par)
        grad_F = q.gradient(par, method='F')

        # par[0] can use the 'A' method, par[1] cannot
        self.assertTrue(q.grad_method_for_par == {0:'A', 1:'F'})
        # the different methods agree
        self.assertAllAlmostEqual(grad, grad_F, delta=tol)


    def test_qnode_fanout(self, qubit_dev1, qubit_dev2, tol):
        "Tests that qnodes can compute the correct function when the same parameter is used in multiple gates."

        def circuit(reused_param, other_param):
            qm.RX(reused_param, [0])
            qm.RZ(other_param, [0])
            qm.RX(reused_param, [0])
            return qm.expectation.PauliZ(0)

        f = qm.QNode(circuit, qubit_dev1)

        for reused_param in thetas:
            for theta in thetas:
                other_param = theta ** 2 / 11
                y_eval = f(reused_param, other_param)
                Rx = frx(reused_param)
                Rz = frz(other_param)
                zero_state = np.array([1.,0.])
                final_state = (Rx @ Rz @ Rx @ zero_state)
                y_true = expZ(final_state)
                self.assertAlmostEqual(y_eval, y_true, delta=tol)

    def test_array_parameters_evaluate(self, qubit_dev1, qubit_dev2, tol):
        "Test that array parameters gives same result as positional arguments."

        a, b, c = 0.5, 0.54, 0.3

        def ansatz(x, y, z):
            qm.QubitStateVector(np.array([1, 0, 1, 1])/np.sqrt(3), [0, 1])
            qm.Rot(x, y, z, 0)
            qm.CNOT([0, 1])
            return qm.expectation.PauliZ(0), qm.expectation.PauliY(1)

        def circuit1(x, y, z):
            return ansatz(x, y, z)

        def circuit2(x, array):
            return ansatz(x, array[0], array[1])

        def circuit3(array):
            return ansatz(*array)

        circuit1 = qm.QNode(circuit1, qubit_dev2)
        positional_res = circuit1(a, b, c)
        positional_grad = circuit1.gradient([a, b, c])

        circuit2 = qm.QNode(circuit2, qubit_dev2)
        array_res = circuit2(a, np.array([b, c]))
        array_grad = circuit2.gradient([a, np.array([b, c])])

        list_res = circuit2(a, [b, c])
        list_grad = circuit2.gradient([a, [b, c]])

        self.assertAllAlmostEqual(positional_res, array_res, delta=tol)
        self.assertAllAlmostEqual(positional_grad, array_grad, delta=tol)

        circuit3 = qm.QNode(circuit3, qubit_dev2)
        array_res = circuit3(np.array([a, b, c]))
        array_grad = circuit3.gradient([np.array([a, b, c])])

        list_res = circuit3([a, b, c])
        list_grad = circuit3.gradient([[a, b, c]])

        self.assertAllAlmostEqual(positional_res, array_res, delta=tol)
        self.assertAllAlmostEqual(positional_grad, array_grad, delta=tol)

    def test_array_parameters_autograd(self, qubit_dev1, qubit_dev2, tol):
        "Test that array parameters autograd gives same result as positional arguments."

        a, b, c = 0.5, 0.54, 0.3

        def ansatz(x, y, z):
            qm.QubitStateVector(np.array([1, 0, 1, 1])/np.sqrt(3), [0, 1])
            qm.Rot(x, y, z, 0)
            qm.CNOT([0, 1])
            return qm.expectation.PauliZ(0)

        def circuit1(x, y, z):
            return ansatz(x, y, z)

        def circuit2(x, array):
            return ansatz(x, array[0], array[1])

        def circuit3(array):
            return ansatz(*array)

        circuit1 = qm.QNode(circuit1, qubit_dev2)
        grad1 = autograd.grad(circuit1, argnum=[0, 1, 2])

        positional_grad = circuit1.gradient([a, b, c])
        positional_autograd = grad1(a, b, c)
        self.assertAllAlmostEqual(positional_grad, positional_autograd, delta=tol)

        circuit2 = qm.QNode(circuit2, qubit_dev2)
        grad2 = autograd.grad(circuit2, argnum=[0, 1])

        # NOTE: Mixing array and positional arguments doesn't seem to work with autograd!
        # array_grad = circuit2.gradient([a, np.array([b, c])])
        # array_autograd = grad2(a, np.array([b, c]))
        # array_autograd_flat = list(_flatten(array_autograd))
        # self.assertAllAlmostEqual(array_grad, array_autograd_flat, delta=tol)

        circuit3 = qm.QNode(circuit3, qubit_dev2)
        grad3 = autograd.grad(circuit3)

        array_grad = circuit3.gradient([np.array([a, b, c])])
        array_autograd = grad3(np.array([a, b, c]))
        self.assertAllAlmostEqual(array_grad, array_autograd, delta=tol)


    @staticmethod
    def expected_jacobian(x, y, z):
        dw0dx = 2/3*np.sin(x)*np.sin(y)
        dw0dy = 1/3*(np.sin(y)-2*np.cos(x)*np.cos(y))
        dw0dz = 0

        dw1dx = -2/3*np.cos(x)*np.sin(y)
        dw1dy = -2/3*np.cos(y)*np.sin(x)
        dw1dz = 0

        return np.array([[dw0dx, dw0dy, dw0dz],
                         [dw1dx, dw1dy, dw1dz]])

    def test_multiple_expectation_different_wires(self, qubit_dev2, tol):
        "Tests that qnodes return multiple expectation values."

        a, b, c = 0.5, 0.54, 0.3

        @qm.qfunc(qubit_dev2)
        def circuit(x, y, z):
            qm.RX(x, [0])
            qm.RZ(y, [0])
            qm.CNOT([0, 1])
            qm.RY(y, [0])
            qm.RX(z, [0])
            return qm.expectation.PauliY(0), qm.expectation.PauliZ(1)

        res = circuit(a, b, c)

        out_state = np.kron(frx(c), I) @ np.kron(fry(b), I) @ CNOT \
            @ np.kron(frz(b), I) @ np.kron(frx(a), I) @ np.array([1, 0, 0, 0])

        ex0 = np.vdot(out_state, np.kron(Y, I) @ out_state)
        ex1 = np.vdot(out_state, np.kron(I, Z) @ out_state)
        ex = np.array([ex0, ex1])
        self.assertAllAlmostEqual(ex, res, delta=tol)

    def test_multiple_expectation_jacobian_positional(self, qubit_dev2, tol):
        "Tests that qnodes using positional arguments return multiple expectation values."

        a, b, c = 0.5, 0.54, 0.3

        def circuit(x, y, z):
            qm.QubitStateVector(np.array([1, 0, 1, 1])/np.sqrt(3), [0, 1])
            qm.Rot(x, y, z, 0)
            qm.CNOT([0, 1])
            return qm.expectation.PauliZ(0), qm.expectation.PauliY(1)

        circuit = qm.QNode(circuit, qubit_dev2)

        # compare our manual Jacobian computation to theoretical result
        # Note: circuit.gradient actually returns a full jacobian in this case
        res = circuit.gradient(np.array([a, b, c]))
        self.assertAllAlmostEqual(self.expected_jacobian(a, b, c), res, delta=tol)

        # compare our manual Jacobian computation to autograd
        # not sure if this is the intended usage of jacobian
        jac0 = autograd.jacobian(circuit, 0)
        jac1 = autograd.jacobian(circuit, 1)
        jac2 = autograd.jacobian(circuit, 2)
        res = np.stack([jac0(a,b,c), jac1(a,b,c), jac2(a,b,c)]).T

        self.assertAllAlmostEqual(self.expected_jacobian(a, b, c), res, delta=tol)

    def test_multiple_expectation_jacobian_array(self, qubit_dev2, tol):
        "Tests that qnodes using an array argument return multiple expectation values."

        a, b, c = 0.5, 0.54, 0.3

        def circuit(weights):
           qm.QubitStateVector(np.array([1, 0, 1, 1])/np.sqrt(3), [0, 1])
           qm.Rot(weights[0], weights[1], weights[2], 0)
           qm.CNOT([0, 1])
           return qm.expectation.PauliZ(0), qm.expectation.PauliY(1)

        circuit = qm.QNode(circuit, qubit_dev2)

        res = circuit.gradient([np.array([a, b, c])])
        self.assertAllAlmostEqual(self.expected_jacobian(a, b, c), res, delta=tol)

        jac = autograd.jacobian(circuit, 0)
        res = jac(np.array([a, b, c]))
        self.assertAllAlmostEqual(self.expected_jacobian(a, b, c), res, delta=tol)
