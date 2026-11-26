from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic_ai.toolsets import FunctionToolset

from knowledge_agent.config import Settings
from knowledge_agent.reasoning import build_agent, build_model
from knowledge_agent.skills import (
    INVARIANTS,
    SkillError,
    load_skills,
)

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / "skills"


def _skill_file(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


async def test_loads_repository_skills_in_order() -> None:
    bundle = await load_skills(SKILLS_DIR)

    assert [skill.name for skill in bundle.skills] == [
        "knowledge-search",
        "answer-synthesis",
    ]
    for skill in bundle.skills:
        assert skill.version != "unversioned"
        assert skill.digest == hashlib.sha256(_skill_file(skill.name).read_bytes()).hexdigest()
    assert "knowledge-search@2" in bundle.summary
    assert "answer-synthesis@2" in bundle.summary


async def test_instructions_combine_invariants_and_skills() -> None:
    bundle = await load_skills(SKILLS_DIR)

    assert bundle.instructions.startswith(INVARIANTS)
    assert "# Skill: knowledge-search" in bundle.instructions
    assert "# Skill: answer-synthesis" in bundle.instructions
    assert "Skill directory:" not in bundle.instructions
    assert str(SKILLS_DIR) not in bundle.instructions


async def test_missing_directory_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(SkillError) as exc_info:
        await load_skills(tmp_path / "absent")

    assert "is not a directory" in str(exc_info.value)


async def test_malformed_skill_is_a_configuration_error(tmp_path: Path) -> None:
    skill = tmp_path / "broken"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")

    with pytest.raises(SkillError) as exc_info:
        await load_skills(tmp_path)

    assert "unusable skills" in str(exc_info.value)


async def test_skill_name_must_match_its_directory(tmp_path: Path) -> None:
    skill = tmp_path / "search"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: knowledge-search\n"
        "description: mismatched name\n"
        "version: 1\n"
        "---\n\n"
        "body\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillError) as exc_info:
        await load_skills(tmp_path)

    assert "unusable skills" in str(exc_info.value)


async def test_skill_text_cannot_change_the_tool_surface() -> None:
    bundle = await load_skills(SKILLS_DIR)
    settings = Settings.from_env(
        {
            "AGENT_LLM_BASE_URL": "https://model.example.com/v1",
            "AGENT_LLM_MODEL": "vendor/model",
            "AGENT_LLM_API_KEY": "secret",
        }
    )

    agent = build_agent(build_model(settings.llm), settings.llm, bundle.instructions)

    names: set[str] = set()
    for toolset in agent.toolsets:
        if isinstance(toolset, FunctionToolset):
            names.update(toolset.tools)
    assert names == {"search_knowledge"}
