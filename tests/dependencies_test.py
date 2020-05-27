import os
import subprocess
import sys
import unittest
import unittest.mock as mock

from imagemounter.dependencies import (CommandDependency, Dependency,
                                       DependencySection, MagicDependency, PythonModuleDependency, require)
from imagemounter.exceptions import CommandNotFoundError


class DependencyTest(unittest.TestCase):

    @unittest.skip("depends on previous output of imount --check")
    def test_imount_check_output(self):
        # This test can be used to verify that the output of ``imount --check``
        # hasn't changed. To use this, first run:
        #    imount --check > ~/imount-check-results.txt
        # Then make any code changes and run this test (remove @unittest.skip).
        self.maxDiff = None
        expected = open(os.path.expanduser("~/imount-check-results.txt")).read()
        actual = subprocess.check_output(['imount', '--check']).decode("utf-8")

        self.assertEqual(expected, actual)


class CommandDependencyTest(unittest.TestCase):

    def test_existing_dependency(self):
        dep = CommandDependency('ls')
        self.assertTrue(dep.is_available)
        dep.require()

    def test_existing_dependency_decorator(self):
        dep = CommandDependency('ls')

        @require(dep)
        def test(x, y):
            return x + y
        self.assertEqual(test(1, 2), 3)

    def test_missing_dependency(self):
        dep = CommandDependency('lsxxxx')
        self.assertFalse(dep.is_available)
        self.assertRaises(CommandNotFoundError, dep.require)

    def test_missing_dependency_decorator(self):
        dep = CommandDependency('lsxxxx')

        @require(dep)
        def test(x, y):
            return x + y
        self.assertRaises(CommandNotFoundError, test)

        @require(dep, none_on_failure=True)
        def test2(x, y):
            return x + y
        self.assertEqual(None, test2(1, 2))

    @mock.patch('imagemounter.dependencies._util')
    def test_mocked_dependency(self, util):
        util.command_exists.return_value = True
        dep = CommandDependency('lsxxxx')
        self.assertTrue(dep.is_available)
        self.assertEqual(dep.printable_status, "INSTALLED lsxxxx")

    @mock.patch('imagemounter.dependencies._util')
    def test_dependency_status_message(self, util):
        util.command_exists.return_value = False
        dep = CommandDependency('ls')
        self.assertFalse(dep.is_available)
        self.assertEqual(dep.printable_status.strip(), "MISSING   ls")

    @mock.patch('imagemounter.dependencies._util')
    def test_dependency_status_message_package(self, util):
        util.command_exists.return_value = False
        dep = CommandDependency('ls', package="core-utils")
        self.assertFalse(dep.is_available)
        expected = "MISSING   ls                  part of the core-utils package"
        self.assertEqual(dep.printable_status.strip(), expected)

    @mock.patch('imagemounter.dependencies._util')
    def test_dependency_status_message_why(self, util):
        util.command_exists.return_value = False
        dep = CommandDependency('ls', why="listing files")
        self.assertFalse(dep.is_available)
        expected = "MISSING   ls                  needed for listing files"
        self.assertEqual(dep.printable_status.strip(), expected)

    @mock.patch('imagemounter.dependencies._util')
    def test_dependency_status_message_package_why(self, util):
        util.command_exists.return_value = False
        dep = CommandDependency('ls', package="core-utils", why="listing files")
        self.assertFalse(dep.is_available)
        expected = "MISSING   ls                  needed for listing files, part of the core-utils package"
        self.assertEqual(dep.printable_status.strip(), expected)


class PythonModuleDependencyTest(unittest.TestCase):

    def test_existing_dependency(self):
        dep = PythonModuleDependency('sys')
        self.assertTrue(dep.is_available)

    def test_missing_dependency(self):
        dep = PythonModuleDependency('foobarnonexistent')
        self.assertFalse(dep.is_available)

    @mock.patch('imagemounter.dependencies._util')
    def test_mocked_dependency(self, util):
        util.module_exists.return_value = True
        dep = PythonModuleDependency('requests2')
        self.assertTrue(dep.is_available)
        self.assertEqual(dep.printable_status, "INSTALLED requests2")

    @mock.patch('imagemounter.dependencies._util')
    def test_mocked_status_message(self, util):
        util.module_exists.return_value = False
        dep = PythonModuleDependency('sys')
        self.assertFalse(dep.is_available)
        expected = "MISSING   sys                 install using pip"
        self.assertEqual(dep.printable_status, expected)

    @mock.patch('imagemounter.dependencies._util')
    def test_mocked_status_message_why(self, util):
        util.module_exists.return_value = False
        dep = PythonModuleDependency('sys', why="system functions")
        self.assertFalse(dep.is_available)
        expected = "MISSING   sys                 needed for system functions, install using pip"
        self.assertEqual(dep.printable_status, expected)


class MagicDependencyTest(unittest.TestCase):

    def setUp(self):
        self.magic = MagicDependency("python-magic")

    def tearDown(self):
        # After each test, remove the fake "magic" module we've created.
        if 'magic' in sys.modules:
            del sys.modules['magic']

    @mock.patch('imagemounter.dependencies._util')
    def test_not_exists(self, util):
        util.module_exists.return_value = False
        self.assertFalse(self.magic.is_available)
        self.assertFalse(self.magic._importable)
        expected = "MISSING   python-magic        install using pip"
        self.assertEqual(self.magic.printable_status, expected)

    def test_exists_pypi(self):
        sys.modules['magic'] = mock.Mock(['from_file'])
        self.assertTrue(self.magic.is_available)
        self.assertTrue(self.magic.is_python_package)
        self.assertFalse(self.magic.is_system_package)
        expected = "INSTALLED python-magic        (Python package)"
        self.assertEqual(self.magic.printable_status, expected)

    def test_exists_system(self):
        sys.modules['magic'] = mock.Mock(['open'])
        self.assertTrue(self.magic.is_available)
        self.assertFalse(self.magic.is_python_package)
        self.assertTrue(self.magic.is_system_package)
        expected = "INSTALLED python-magic        (system package)"
        self.assertEqual(self.magic.printable_status, expected)

    def test_exists_unknown(self):
        sys.modules['magic'] = mock.Mock([])
        self.assertTrue(self.magic._importable)
        self.assertFalse(self.magic.is_available)
        self.assertFalse(self.magic.is_python_package)
        self.assertFalse(self.magic.is_system_package)
        expected = "ERROR     python-magic        expecting python-magic, found other module named magic"
        self.assertEqual(self.magic.printable_status, expected)


class DependencySectionTest(unittest.TestCase):

    def test_section_no_deps(self):
        section = DependencySection(name="empty section",
                                    description='not needed',
                                    deps=[])

        expected = "-- empty section (not needed) --"
        self.assertEqual(expected, section.printable_status)

    def test_section_printable_status(self):
        mock_dependency = mock.Mock()
        mock_dependency.printable_status = "I'm just a mock"
        section = DependencySection(name="fake section",
                                    description='needed for stuff',
                                    deps=[mock_dependency])

        expected = "-- fake section (needed for stuff) --\n I'm just a mock"
        self.assertEqual(expected, section.printable_status)