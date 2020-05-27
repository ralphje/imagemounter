import os
import os.path
import sys
from invoke import run, task


@task
def clean(ctx):
    run('git clean -Xfd')


@task
def test(ctx):
    print('Python version: ' + sys.version)

    cwp = os.path.dirname(os.path.abspath(__name__))
    pythonpath = os.environ.get('PYTHONPATH', '').split(os.pathsep)
    pythonpath.append(os.path.join(cwp, 'tests'))
    os.environ['PYTHONPATH'] = os.pathsep.join(pythonpath)

    test_flake(ctx)
    run('coverage run --source=imagemounter --branch `which pytest`')
    run('coverage report')


@task
def test_flake(ctx):
    run('flake8 --ignore=W801,E128,E501,W402,W503 imagemounter')


@task
def docs(ctx):
    run('cd docs; make html; cd ..')
