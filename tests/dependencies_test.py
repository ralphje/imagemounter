import sys

import pytest

from imagemounter.dependencies import CommandDependency, DependencySection, MagicDependency, PythonModuleDependency, \
    require, FileSystemTypeDependency
from imagemounter.exceptions import CommandNotFoundError, ModuleNotFoundError, PrerequisiteFailedError


class TestDependencyDecorator:
    @pytest.mark.parametrize("none_on_failure", [True, False])
    def test_existing_dependency(self, none_on_failure):
        dep = CommandDependency('ls')

        @require(dep, none_on_failure=none_on_failure)
        def test(x, y):
            return x + y

        assert test(1, 2) == 3

    def test_missing_dependency(self):
        dep = CommandDependency('lsxxxx')

        @require(dep)
        def test(x, y):
            return x + y

        with pytest.raises(CommandNotFoundError):
            test()

    def test_missing_dependency_none_on_failure(self):
        dep = CommandDependency('lsxxxx')

        @require(dep, none_on_failure=True)
        def test2(x, y):
            return x + y

        assert test2(1, 2) is None


class TestCommandDependency:
    def test_existing_dependency(self):
        dep = CommandDependency('ls')
        assert dep.is_available
        dep.require()

    def test_missing_dependency(self):
        dep = CommandDependency('lsxxxx')
        assert not dep.is_available
        with pytest.raises(CommandNotFoundError):
            dep.require()

    def test_status_message_existing(self, mocker):
        util = mocker.patch('imagemounter.dependencies._util')
        util.command_exists.return_value = True

        dep = CommandDependency('lsxxxx')
        assert dep.is_available
        assert dep.printable_status == "INSTALLED lsxxxx"

    @pytest.mark.parametrize("args,result", [
        ({}, "MISSING   ls"),
        (dict(package="core-utils"), "MISSING   ls                  part of the core-utils package"),
        (dict(why="listing files"),  "MISSING   ls                  needed for listing files"),
        (dict(package="core-utils", why="listing files"),
         "MISSING   ls                  needed for listing files, part of the core-utils package"),
    ])
    def test_status_message_missing(self, mocker, args, result):
        util = mocker.patch('imagemounter.dependencies._util')
        util.command_exists.return_value = False

        dep = CommandDependency('ls', **args)
        assert not dep.is_available
        assert dep.printable_status.strip() == result


class TestFilesystemDependency:
    def test_existing_dependency(self):
        dep = FileSystemTypeDependency('tmpfs')
        assert dep.is_available
        dep.require()

    def test_existing_unloaded_dependency(self, mocker):
        # this assumes iso9660 is a kernel dependency available
        dep = FileSystemTypeDependency('iso9660')
        dep._is_loaded = mocker.Mock(return_value=False)
        assert dep.is_available
        dep.require()

    def test_missing_dependency(self):
        dep = CommandDependency('foobar')
        assert not dep.is_available
        with pytest.raises(PrerequisiteFailedError):
            dep.require()


class TestPythonModuleDependency:
    def test_existing_dependency(self):
        dep = PythonModuleDependency('sys')
        assert dep.is_available
        dep.require()

    def test_missing_dependency(self):
        dep = PythonModuleDependency('foobarnonexistent')
        assert not dep.is_available
        with pytest.raises(ModuleNotFoundError):
            dep.require()

    def test_status_message_existing(self, mocker):
        util = mocker.patch('imagemounter.dependencies._util')
        util.module_exists.return_value = True

        dep = PythonModuleDependency('requests2')
        assert dep.is_available
        assert dep.printable_status == "INSTALLED requests2"

    @pytest.mark.parametrize("args,result", [
        ({}, "MISSING   sys                 install using pip"),
        (dict(why="system functions"), "MISSING   sys                 needed for system functions, install using pip"),
    ])
    def test_status_message_missing(self, mocker, args, result):
        util = mocker.patch('imagemounter.dependencies._util')
        util.module_exists.return_value = False

        dep = PythonModuleDependency('sys', **args)
        assert not dep.is_available
        assert dep.printable_status.strip() == result


class TestMagicDependency:
    @pytest.fixture
    def magic_dep(self):
        return MagicDependency("python-magic")

    @pytest.fixture
    def magic_pypi(self, mocker):
        sys.modules['magic'] = mocker.Mock(['from_file'])
        yield sys.modules['magic']
        del sys.modules['magic']

    @pytest.fixture
    def magic_system(self, mocker):
        sys.modules['magic'] = mocker.Mock(['open'])
        yield sys.modules['magic']
        del sys.modules['magic']

    @pytest.fixture
    def magic_unknown(self, mocker):
        sys.modules['magic'] = mocker.Mock([])
        yield sys.modules['magic']
        del sys.modules['magic']

    def test_not_exists(self, mocker, magic_dep):
        util = mocker.patch('imagemounter.dependencies._util')
        util.module_exists.return_value = False

        assert not magic_dep.is_available
        assert not magic_dep._importable
        assert magic_dep.printable_status == "MISSING   python-magic        install using pip"

    def test_exists_pypi(self, magic_dep, magic_pypi):
        assert magic_dep.is_available
        assert magic_dep.is_python_package
        assert not magic_dep.is_system_package
        assert magic_dep.printable_status == "INSTALLED python-magic        (Python package)"

    def test_exists_system(self, magic_dep, magic_system):
        assert magic_dep.is_available
        assert not magic_dep.is_python_package
        assert magic_dep.is_system_package
        assert magic_dep.printable_status == "INSTALLED python-magic        (system package)"

    def test_exists_unknown(self, magic_dep, magic_unknown):
        assert magic_dep._importable
        assert not magic_dep.is_available
        assert not magic_dep.is_python_package
        assert not magic_dep.is_system_package
        assert magic_dep.printable_status \
               == "ERROR     python-magic        expecting python-magic, found other module named magic"


class TestDependencySection:
    def test_section_no_deps(self):
        section = DependencySection(name="empty section",
                                    description='not needed',
                                    deps=[])
        assert section.printable_status == "-- empty section (not needed) --"

    def test_section_printable_status(self, mocker):
        mock_dependency = mocker.Mock()
        mock_dependency.printable_status = "I'm just a mock"
        section = DependencySection(name="fake section",
                                    description='needed for stuff',
                                    deps=[mock_dependency])

        assert section.printable_status == "-- fake section (needed for stuff) --\n I'm just a mock"
