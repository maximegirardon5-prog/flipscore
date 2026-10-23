"""Test minimal : le projet s'importe et la suite de tests tourne."""

import app


def test_project_imports():
    assert app.__version__
