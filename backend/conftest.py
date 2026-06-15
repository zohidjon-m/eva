"""Pytest configuration for the Eva backend test suite.

Its mere presence at ``backend/`` makes pytest treat this directory as the
rootdir and put it on ``sys.path``, so tests can ``import memory`` / ``import
llm`` exactly as the running app does — no package install or PYTHONPATH dance.
"""
