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
Unit tests for the :mod:`openqml` configuration classe :class:`Configuration`.
"""
import os

import numpy as np
import numpy.random as nr

import toml

from conftest import BaseTest

import openqml as qm
from openqml import Configuration


filename = 'default_config.toml'
expected_config = toml.load(filename)

class TestBasic(BaseTest):
    """Configuration class tests."""

    def test_loading_current_directory(self, tol):
        """Test that the default configuration file can be loaded
        from the current directory."""

        os.curdir = "."
        os.environ["OPENQML_CONF"] = ""
        config = Configuration(name=filename)

        self.assertEqual(config._config, expected_config)
        self.assertEqual(config.path, os.path.join(os.curdir, filename))

    def test_loading_environment_variable(self, tol):
        """Test that the default configuration file can be loaded
        from an environment variable."""

        os.curdir = "None"
        os.environ["OPENQML_CONF"] = os.getcwd()
        config = Configuration(name=filename)

        self.assertEqual(config._config, expected_config)
        self.assertEqual(config._env_config_dir, os.environ["OPENQML_CONF"])
        self.assertEqual(config.path, os.path.join(os.environ["OPENQML_CONF"], filename))

    def test_loading_absolute_path(self, tol):
        """Test that the default configuration file can be loaded
        from an absolute path."""

        os.curdir = "None"
        os.environ["OPENQML_CONF"] = ""
        config = Configuration(name=os.path.join(os.getcwd(), filename))

        self.assertEqual(config._config, expected_config)
        self.assertEqual(config.path, os.path.join(os.getcwd(), filename))

    # def test_not_found_warning(self, tol):
    #     """Test that a warning is raised if no configuration file found."""

    #     with self.assertLogs(level='WARNING') as l:
    #         config = Configuration()
    #         self.assertEqual(len(l.output), 1)
    #         self.assertEqual(len(l.records), 1)
    #         self.assertIn('No OpenQML configuration file found.', l.output[0])

    def test_save(self, tol):
        """Test saving a configuration file."""

        config = Configuration(name=filename)

        # make a change
        config['strawberryfields.global']['shots'] = 10
        config.save('test_config.toml')

        result = toml.load('test_config.toml')
        os.remove('test_config.toml')
        self.assertEqual(config._config, result)

    def test_get_item(self, tol):
        """Test getting items."""

        config = Configuration(name=filename)

        # get existing options
        self.assertEqual(config['main.shots'], 0)
        self.assertEqual(config['main']['shots'], 0)
        self.assertEqual(config['strawberryfields.global.hbar'], 1)
        self.assertEqual(config['strawberryfields.global']['hbar'], 1)

        # get nested dictionaries
        self.assertEqual(config['strawberryfields.fock'], {'cutoff_dim': 10})

        # get key that doesn't exist
        self.assertEqual(config['projectq.ibmbackend.cutoff'], {})

    def test_set_item(self, tol):
        """Test setting items."""

        config = Configuration(name=filename)

        # set existing options
        config['main.shots'] = 10
        self.assertEqual(config['main.shots'], 10)
        self.assertEqual(config['main']['shots'], 10)

        config['strawberryfields.global']['hbar'] = 5
        self.assertEqual(config['strawberryfields.global.hbar'], 5)
        self.assertEqual(config['strawberryfields.global']['hbar'], 5)

        # set new options
        config['projectq.ibmbackend']['device'] = 'ibmqx4'
        self.assertEqual(config['projectq.ibmbackend.device'], 'ibmqx4')

        # set nested dictionaries
        config['strawberryfields.tf'] = {'batched': True, 'cutoff_dim': 6}
        self.assertEqual(config['strawberryfields.tf'], {'batched': True, 'cutoff_dim': 6})

        # set nested keys that don't exist dictionaries
        config['strawberryfields.another.hello.world'] = 5
        self.assertEqual(config['strawberryfields.another'], {'hello': {'world': 5}})

    def test_bool(self, tol):
        """Test boolean value of the Configuration object."""

        # test false if no config is loaded
        config = Configuration()
        self.assertFalse(config)

        # test true if config is loaded
        config = Configuration(filename)
        self.assertTrue(config)
