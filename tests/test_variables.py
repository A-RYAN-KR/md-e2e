"""Unit tests for the VariableStore and variable interpolation engine."""

import os
import pytest
from unittest import mock
from md_e2e.variables import VariableStore, UndefinedVariableError


class TestVariableStore:
    def test_store_and_get(self):
        store = VariableStore()
        store.store("username", "admin")
        assert store.get("username") == "admin"

    def test_has_variable(self):
        store = VariableStore()
        assert not store.has("username")
        store.store("username", "admin")
        assert store.has("username")

    def test_initial_values(self):
        store = VariableStore({"foo": "bar", "baz": "qux"})
        assert store.get("foo") == "bar"
        assert store.get("baz") == "qux"

    def test_undefined_variable_error(self):
        store = VariableStore()
        with pytest.raises(UndefinedVariableError) as exc_info:
            store.get("missing")
        assert "Variable 'missing' is not defined in VariableStore" in str(exc_info.value)
        assert exc_info.value.line_number is None

    def test_undefined_variable_error_with_line(self):
        store = VariableStore()
        with pytest.raises(UndefinedVariableError) as exc_info:
            store.resolve("Hello {{ missing }}", line_number=42)
        assert "Variable 'missing' at line 42 is not defined in VariableStore" in str(exc_info.value)
        assert exc_info.value.line_number == 42

    def test_resolve_jinja_style(self):
        store = VariableStore({"name": "Alice", "role": "admin"})
        assert store.resolve("Hello {{name}}!") == "Hello Alice!"
        assert store.resolve("Hello {{ name }}!") == "Hello Alice!"
        assert store.resolve("Hello {{  name  }}!") == "Hello Alice!"
        assert store.resolve("User: {{name}} is {{role}}") == "User: Alice is admin"

    def test_resolve_shell_style(self):
        store = VariableStore({"BASE_URL": "https://example.com"})
        assert store.resolve("Navigate to ${BASE_URL}/dashboard") == "Navigate to https://example.com/dashboard"

    def test_resolve_mixed_styles(self):
        store = VariableStore({"name": "Bob", "KEY": "secret"})
        assert store.resolve("User {{name}} with key ${KEY}") == "User Bob with key secret"

    def test_built_in_generators_random_string(self):
        store = VariableStore()
        assert store.has("RANDOM_STRING")
        val1 = store.get("RANDOM_STRING")
        assert len(val1) == 12
        assert val1.isalnum()
        # Verify caching (accessing again gives the same value)
        assert store.get("RANDOM_STRING") == val1

    def test_built_in_generators_random_email(self):
        store = VariableStore()
        assert store.has("RANDOM_EMAIL")
        val1 = store.get("RANDOM_EMAIL")
        assert val1.startswith("test_")
        assert val1.endswith("@example.com")
        # Verify caching
        assert store.get("RANDOM_EMAIL") == val1

    def test_built_in_generators_timestamp(self):
        store = VariableStore()
        assert store.has("TIMESTAMP")
        val1 = store.get("TIMESTAMP")
        assert val1.isdigit()
        # Verify caching
        assert store.get("TIMESTAMP") == val1

    def test_env_vars_mapping(self):
        store = VariableStore()
        assert not store.has("ENV_TEST_VAR")
        
        with mock.patch.dict(os.environ, {"TEST_VAR": "env_value_123"}):
            assert store.has("ENV_TEST_VAR")
            assert store.get("ENV_TEST_VAR") == "env_value_123"
            
        # If env var is deleted, it should fail to get unless cached
        with pytest.raises(UndefinedVariableError):
            store.get("ENV_TEST_VAR")

    def test_snapshot_and_merge(self):
        store = VariableStore({"a": "1", "b": "2"})
        snapshot = store.snapshot()
        assert snapshot == {"a": "1", "b": "2"}
        
        # Merge is non-mutating
        merged = store.merge({"b": "3", "c": "4"})
        assert store.get("b") == "2"  # original unchanged
        assert merged.get("a") == "1"
        assert merged.get("b") == "3"
        assert merged.get("c") == "4"
