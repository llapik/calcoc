"""Tests for AI engine and related modules."""

import pytest
import yaml

from src.core.config import Config
from src.ai.engine import AIEngine
from src.ai.prompts import get_system_prompt, build_context_message
from src.ai.rag import KnowledgeBase


@pytest.fixture
def config_no_ai(tmp_path):
    settings = {"ai": {"backend": "none"}, "app": {"language": "ru"}}
    with open(tmp_path / "settings.yaml", "w") as fh:
        yaml.dump(settings, fh)
    with open(tmp_path / "models.yaml", "w") as fh:
        yaml.dump({"models": []}, fh)
    with open(tmp_path / "safety_rules.yaml", "w") as fh:
        yaml.dump({}, fh)
    return Config(tmp_path)


class TestPrompts:
    def test_russian_prompt(self):
        prompt = get_system_prompt("ru")
        assert "диагностик" in prompt.lower()

    def test_english_prompt(self):
        prompt = get_system_prompt("en")
        assert "diagnostic" in prompt.lower()

    def test_context_message(self):
        msg = build_context_message(
            system_info="CPU: Test",
            problems="No problems",
            user_message="Hello",
        )
        assert "CPU: Test" in msg
        assert "Hello" in msg


class TestAIEngineNoBackend:
    def test_rule_based_response_scan(self, config_no_ai):
        engine = AIEngine(config_no_ai)
        response = engine.chat("Запусти диагностику")
        assert response  # Should return something even without AI
        assert "модель не загружена" in response.lower() or "/scan" in response.lower()

    def test_rule_based_response_upgrade(self, config_no_ai):
        engine = AIEngine(config_no_ai)
        response = engine.chat("Как улучшить компьютер?")
        assert response

    def test_backend_name(self, config_no_ai):
        engine = AIEngine(config_no_ai)
        engine.ensure_ready()
        assert engine.backend_name == "none"

    def test_not_available(self, config_no_ai):
        engine = AIEngine(config_no_ai)
        assert engine.is_available is False


class TestKnowledgeBase:
    def test_load_documents(self, tmp_path):
        import json
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()
        data = {"entries": [
            {"title": "Test Fix", "category": "test", "content": "Fix the problem by restarting"},
            {"title": "SSD Upgrade", "category": "upgrade", "content": "Replace HDD with SSD for speed"},
        ]}
        with open(kb_dir / "test.json", "w") as fh:
            json.dump(data, fh)

        kb = KnowledgeBase(kb_dir)
        assert len(kb._documents) == 2

    def test_keyword_search(self, tmp_path):
        import json
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()
        data = {"entries": [
            {"title": "SSD", "content": "SSD is faster than HDD"},
            {"title": "RAM", "content": "More RAM helps multitasking"},
        ]}
        with open(kb_dir / "test.json", "w") as fh:
            json.dump(data, fh)

        kb = KnowledgeBase(kb_dir)
        results = kb.search("SSD speed HDD")
        assert len(results) > 0
        assert results[0]["title"] == "SSD"

    def test_empty_knowledge_dir(self, tmp_path):
        kb = KnowledgeBase(tmp_path / "nonexistent")
        results = kb.search("test query")
        assert results == []
