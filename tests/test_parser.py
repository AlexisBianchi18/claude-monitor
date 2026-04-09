"""Tests para log_parser.py — cubre todos los edge cases del plan."""

import json
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_monitor.config import PRICING_TABLE
from claude_monitor.log_parser import ClaudeLogParser
from claude_monitor.models import TokenUsage

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TARGET_DATE = date(2026, 4, 8)
YESTERDAY = date(2026, 4, 7)


@pytest.fixture()
def tmp_logs(tmp_path):
    """Crea un directorio temporal que simula ~/.claude/projects/."""
    return tmp_path


@pytest.fixture()
def project_with_fixtures(tmp_logs):
    """Crea un proyecto con los fixtures de sample_session en la estructura real."""
    project_dir = tmp_logs / "-Users-testuser-Projects-my-cool-project"
    project_dir.mkdir()

    # Copiar session principal
    shutil.copy(FIXTURES_DIR / "sample_session.jsonl", project_dir / "sess-001.jsonl")

    # Crear estructura de subagentes
    subagents_dir = project_dir / "sess-001" / "subagents"
    subagents_dir.mkdir(parents=True)
    shutil.copy(
        FIXTURES_DIR / "sample_subagent.jsonl",
        subagents_dir / "agent-abc123.jsonl",
    )

    return tmp_logs


# --- Directorio inexistente ---


class TestNonExistentDirectory:
    def test_returns_empty_report(self):
        parser = ClaudeLogParser(logs_dir=Path("/nonexistent/path"))
        report = parser.get_daily_report(TARGET_DATE)
        assert report.total_cost == 0.0
        assert report.total_tokens == 0
        assert report.entry_count == 0
        assert report.projects == []
        assert report.date == TARGET_DATE


# --- Archivo vacío ---


class TestEmptyFile:
    def test_empty_file_returns_no_entries(self, tmp_logs):
        project_dir = tmp_logs / "-Users-test-empty"
        project_dir.mkdir()
        shutil.copy(FIXTURES_DIR / "empty.jsonl", project_dir / "session.jsonl")

        parser = ClaudeLogParser(logs_dir=tmp_logs)
        report = parser.get_daily_report(TARGET_DATE)
        assert report.entry_count == 0


# --- Líneas malformadas ---


class TestMalformedLines:
    def test_malformed_file_does_not_crash(self, tmp_logs):
        project_dir = tmp_logs / "-Users-test-malformed"
        project_dir.mkdir()
        shutil.copy(FIXTURES_DIR / "malformed.jsonl", project_dir / "session.jsonl")

        parser = ClaudeLogParser(logs_dir=tmp_logs)
        report = parser.get_daily_report(TARGET_DATE)
        assert report.entry_count == 0


# --- Tipos no-assistant ---


class TestNonAssistantTypes:
    def test_user_entries_ignored(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        # La fixture tiene entries user, queue-operation, attachment, ai-title
        # Solo deben contarse los assistant válidos
        for p in report.projects:
            assert p.entry_count > 0  # tiene assistant entries
        # Verificar que no se contaron los otros tipos:
        # Total entries debería ser solo assistant válidos (dedup + sonnet + haiku sub)
        assert report.entry_count == 3  # msg_dedup_001 (dedup), msg_sonnet_001, msg_haiku_sub_001


# --- Modelo <synthetic> ---


class TestSyntheticModel:
    def test_synthetic_model_ignored(self, tmp_logs):
        project_dir = tmp_logs / "-Users-test-synthetic"
        project_dir.mkdir()
        session_file = project_dir / "session.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": "<synthetic>",
                        "id": "msg_synth",
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                    "timestamp": "2026-04-08T14:00:00.000Z",
                }
            )
            + "\n"
        )

        parser = ClaudeLogParser(logs_dir=tmp_logs)
        report = parser.get_daily_report(TARGET_DATE)
        assert report.entry_count == 0


# --- Deduplicación por message.id ---


class TestDeduplication:
    def test_same_message_id_keeps_last(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)

        # La fixture tiene dos entries con id "msg_dedup_001"
        # El primero: output_tokens=10, el segundo: output_tokens=50
        # Solo debe contarse una vez, con output_tokens=50
        project = report.projects[0]  # mayor costo

        # Buscar la entry de opus en el parser directamente
        project_dir = project_with_fixtures / "-Users-testuser-Projects-my-cool-project"
        entries = parser._parse_jsonl_file(
            project_dir / "sess-001.jsonl", TARGET_DATE
        )
        dedup_entry = [e for e in entries if e.message_id == "msg_dedup_001"]
        assert len(dedup_entry) == 1
        assert dedup_entry[0].usage.output_tokens == 50  # último gana
        assert dedup_entry[0].usage.cache_creation_1h_tokens == 150
        assert dedup_entry[0].usage.cache_creation_5m_tokens == 50


# --- Cálculo de costo correcto ---


class TestCostCalculation:
    def test_opus_cost_with_cache_breakdown(self):
        pricing = PRICING_TABLE["claude-opus-4-6"]
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=200,
            cache_creation_5m_tokens=80,
            cache_creation_1h_tokens=120,
        )
        cost = ClaudeLogParser._calculate_cost("claude-opus-4-6", usage)
        expected = (
            100 * pricing.input
            + 50 * pricing.output
            + 500 * pricing.cache_read
            + 80 * pricing.cache_create_5m
            + 120 * pricing.cache_create_1h
        ) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_sonnet_cost(self):
        pricing = PRICING_TABLE["claude-sonnet-4-6"]
        usage = TokenUsage(input_tokens=200, output_tokens=100)
        cost = ClaudeLogParser._calculate_cost("claude-sonnet-4-6", usage)
        expected = (200 * pricing.input + 100 * pricing.output) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_haiku_cost(self):
        pricing = PRICING_TABLE["claude-haiku-4-5-20251001"]
        usage = TokenUsage(input_tokens=500, output_tokens=200, cache_read_input_tokens=1000)
        cost = ClaudeLogParser._calculate_cost("claude-haiku-4-5-20251001", usage)
        expected = (
            500 * pricing.input + 200 * pricing.output + 1000 * pricing.cache_read
        ) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_unknown_model_returns_zero(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = ClaudeLogParser._calculate_cost("claude-unknown-model", usage)
        assert cost == 0.0

    def test_cache_fallback_all_as_5m(self):
        """Si no hay desglose 1h/5m, todo cache_creation se trata como 5m."""
        pricing = PRICING_TABLE["claude-opus-4-6"]
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=300,
            cache_creation_5m_tokens=300,  # fallback: todo como 5m
            cache_creation_1h_tokens=0,
        )
        cost = ClaudeLogParser._calculate_cost("claude-opus-4-6", usage)
        expected = (
            100 * pricing.input
            + 50 * pricing.output
            + 300 * pricing.cache_create_5m
        ) / 1_000_000
        assert abs(cost - expected) < 1e-10


# --- Filtrado por fecha ---


class TestDateFiltering:
    def test_yesterday_entries_excluded(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)

        # msg_yesterday_001 tiene timestamp 2026-04-07 → no debe aparecer
        project_dir = project_with_fixtures / "-Users-testuser-Projects-my-cool-project"
        entries = parser._parse_jsonl_file(
            project_dir / "sess-001.jsonl", TARGET_DATE
        )
        yesterday_entries = [e for e in entries if e.message_id == "msg_yesterday_001"]
        assert len(yesterday_entries) == 0

    def test_yesterday_report_includes_yesterday_entries(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(YESTERDAY)
        assert report.entry_count == 1  # msg_yesterday_001


# --- Timestamps y timezone ---


class TestTimestamps:
    def test_parse_timestamp_with_z(self):
        ts = ClaudeLogParser._parse_timestamp("2026-04-08T14:00:00.000Z")
        assert ts is not None
        assert ts.tzinfo is not None
        assert ts.year == 2026
        assert ts.month == 4
        assert ts.day == 8

    def test_parse_timestamp_with_offset(self):
        ts = ClaudeLogParser._parse_timestamp("2026-04-08T14:00:00+05:00")
        assert ts is not None

    def test_parse_timestamp_empty(self):
        assert ClaudeLogParser._parse_timestamp("") is None

    def test_parse_timestamp_invalid(self):
        assert ClaudeLogParser._parse_timestamp("not a date") is None

    def test_timestamp_to_local_date(self):
        utc_dt = datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc)
        local_date = ClaudeLogParser._timestamp_to_local_date(utc_dt)
        assert isinstance(local_date, date)


# --- Subagentes ---


class TestSubagents:
    def test_subagent_entries_included(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)

        # Debe incluir msg_haiku_sub_001 del subagente
        assert report.entry_count == 3  # dedup opus + sonnet + haiku sub

    def test_find_session_files_includes_subagents(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        project_dir = (
            project_with_fixtures / "-Users-testuser-Projects-my-cool-project"
        )
        files = parser._find_session_files(project_dir)
        names = [f.name for f in files]
        assert "sess-001.jsonl" in names
        assert "agent-abc123.jsonl" in names


# --- Nombre de proyecto ---


class TestProjectName:
    def test_name_from_cwd(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        project_dir = (
            project_with_fixtures / "-Users-testuser-Projects-my-cool-project"
        )
        files = parser._find_session_files(project_dir)
        name, display_name = parser._extract_project_name(project_dir, files)
        assert name == "my-cool-project"
        assert display_name == "my-cool-project"

    def test_fallback_to_dir_name(self, tmp_logs):
        project_dir = tmp_logs / "-Users-test-no-cwd"
        project_dir.mkdir()
        # Sesión sin entries tipo user (solo assistant)
        session = project_dir / "session.jsonl"
        session.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-opus-4-6",
                        "id": "msg_001",
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    },
                    "timestamp": "2026-04-08T14:00:00.000Z",
                }
            )
            + "\n"
        )

        parser = ClaudeLogParser(logs_dir=tmp_logs)
        files = parser._find_session_files(project_dir)
        name, display_name = parser._extract_project_name(project_dir, files)
        assert name == "-Users-test-no-cwd"


# --- Proyectos ordenados por costo ---


class TestProjectOrdering:
    def test_projects_sorted_by_cost_descending(self, tmp_logs):
        # Crear dos proyectos con diferentes costos
        for proj_name, tokens in [
            ("-Users-test-cheap", 10),
            ("-Users-test-expensive", 10000),
        ]:
            project_dir = tmp_logs / proj_name
            project_dir.mkdir()
            session = project_dir / "session.jsonl"
            lines = [
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": []},
                        "cwd": f"/Users/test/{proj_name.split('-')[-1]}",
                        "timestamp": "2026-04-08T14:00:00.000Z",
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-opus-4-6",
                            "id": f"msg_{proj_name}",
                            "usage": {
                                "input_tokens": tokens,
                                "output_tokens": tokens,
                            },
                        },
                        "timestamp": "2026-04-08T14:00:01.000Z",
                    }
                ),
            ]
            session.write_text("\n".join(lines) + "\n")

        parser = ClaudeLogParser(logs_dir=tmp_logs)
        report = parser.get_daily_report(TARGET_DATE)

        assert len(report.projects) == 2
        assert report.projects[0].total_cost > report.projects[1].total_cost


# --- Entry sin campo usage ---


class TestMissingUsage:
    def test_assistant_without_usage_skipped(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        project_dir = (
            project_with_fixtures / "-Users-testuser-Projects-my-cool-project"
        )
        entries = parser._parse_jsonl_file(
            project_dir / "sess-001.jsonl", TARGET_DATE
        )
        # msg_no_usage_001 no tiene campo usage → debe ser ignorado
        no_usage = [e for e in entries if e.message_id == "msg_no_usage_001"]
        assert len(no_usage) == 0


# --- Tokens individuales faltantes default 0 ---


class TestMissingIndividualTokens:
    def test_missing_cache_tokens_default_zero(self, tmp_logs):
        project_dir = tmp_logs / "-Users-test-partial"
        project_dir.mkdir()
        session = project_dir / "session.jsonl"
        session.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-sonnet-4-6",
                        "id": "msg_partial",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            # sin cache tokens
                        },
                    },
                    "timestamp": "2026-04-08T14:00:00.000Z",
                }
            )
            + "\n"
        )

        parser = ClaudeLogParser(logs_dir=tmp_logs)
        entries = parser._parse_jsonl_file(session, TARGET_DATE)
        assert len(entries) == 1
        assert entries[0].usage.cache_read_input_tokens == 0
        assert entries[0].usage.cache_creation_input_tokens == 0


# --- memory/ directory ignored ---


class TestMemoryDirectoryIgnored:
    def test_memory_dir_skipped(self, tmp_logs):
        # Crear directorio memory que no debe ser parseado
        memory_dir = tmp_logs / "memory"
        memory_dir.mkdir()
        (memory_dir / "something.jsonl").write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-opus-4-6",
                        "id": "msg_mem",
                        "usage": {"input_tokens": 1000, "output_tokens": 500},
                    },
                    "timestamp": "2026-04-08T14:00:00.000Z",
                }
            )
            + "\n"
        )

        parser = ClaudeLogParser(logs_dir=tmp_logs)
        report = parser.get_daily_report(TARGET_DATE)
        assert report.entry_count == 0


# --- .meta.json ignorados ---


class TestMetaJsonIgnored:
    def test_meta_json_not_parsed(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        project_dir = (
            project_with_fixtures / "-Users-testuser-Projects-my-cool-project"
        )
        # Crear un .meta.json
        meta = project_dir / "sess-001" / "subagents" / "agent-abc123.meta.json"
        meta.write_text('{"some": "metadata"}')

        files = parser._find_session_files(project_dir)
        extensions = [f.suffix for f in files]
        assert ".json" not in extensions  # solo .jsonl


class TestTokensByModel:
    def test_tokens_by_model_populated(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        assert isinstance(report.tokens_by_model, dict)
        assert len(report.tokens_by_model) > 0
        assert "claude-opus-4-6" in report.tokens_by_model
        assert "claude-sonnet-4-6" in report.tokens_by_model
        assert "claude-haiku-4-5-20251001" in report.tokens_by_model

    def test_tokens_by_model_sums_correctly(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        model_total = sum(report.tokens_by_model.values())
        assert model_total == report.total_tokens

    def test_tokens_by_model_empty_when_no_data(self):
        parser = ClaudeLogParser(logs_dir=Path("/nonexistent/path"))
        report = parser.get_daily_report(TARGET_DATE)
        assert report.tokens_by_model == {}


class TestEffectiveTokens:
    """Tests para effective_tokens (excluye cache_read_input_tokens)."""

    def test_effective_tokens_excludes_cache_read(self):
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=5000,
            cache_creation_input_tokens=200,
        )
        assert usage.total_tokens == 5350
        assert usage.effective_tokens == 350

    def test_effective_tokens_zero_cache(self):
        usage = TokenUsage(input_tokens=200, output_tokens=100)
        assert usage.effective_tokens == usage.total_tokens == 300

    def test_effective_tokens_by_model_populated(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        assert isinstance(report.effective_tokens_by_model, dict)
        assert "claude-opus-4-6" in report.effective_tokens_by_model
        assert "claude-sonnet-4-6" in report.effective_tokens_by_model
        assert "claude-haiku-4-5-20251001" in report.effective_tokens_by_model

    def test_effective_tokens_less_than_total(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        for model in report.tokens_by_model:
            assert report.effective_tokens_by_model[model] <= report.tokens_by_model[model]

    def test_effective_tokens_by_model_values(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        # opus: input=100 + output=50 + cache_create=200 = 350
        assert report.effective_tokens_by_model["claude-opus-4-6"] == 350
        # sonnet: input=200 + output=100 = 300 (no cache)
        assert report.effective_tokens_by_model["claude-sonnet-4-6"] == 300
        # haiku subagent: input=500 + output=200 = 700 (no cache_create)
        assert report.effective_tokens_by_model["claude-haiku-4-5-20251001"] == 700

    def test_effective_tokens_by_model_empty_when_no_data(self):
        parser = ClaudeLogParser(logs_dir=Path("/nonexistent/path"))
        report = parser.get_daily_report(TARGET_DATE)
        assert report.effective_tokens_by_model == {}

    def test_plan_report_uses_effective_tokens(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        limits = {
            "claude-opus-4-6": 10_000_000,
            "claude-sonnet-4-6": 50_000_000,
            "claude-haiku-4-5-20251001": 150_000_000,
        }
        plan = parser.get_plan_report("max_5x", limits, target_date=TARGET_DATE)
        opus = next(m for m in plan.models if "opus" in m.model)
        # Debe usar effective_tokens (350), no total_tokens (850)
        assert opus.tokens_used == 350
        assert opus.percentage == pytest.approx(350 / 10_000_000 * 100)


class TestCostByModel:
    def test_cost_by_model_populated(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        assert isinstance(report.cost_by_model, dict)
        assert len(report.cost_by_model) > 0
        assert "claude-opus-4-6" in report.cost_by_model
        assert "claude-sonnet-4-6" in report.cost_by_model
        assert "claude-haiku-4-5-20251001" in report.cost_by_model

    def test_cost_by_model_sums_to_total(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        report = parser.get_daily_report(TARGET_DATE)
        model_total = sum(report.cost_by_model.values())
        assert abs(model_total - report.total_cost) < 1e-10

    def test_cost_by_model_empty_when_no_data(self):
        parser = ClaudeLogParser(logs_dir=Path("/nonexistent/path"))
        report = parser.get_daily_report(TARGET_DATE)
        assert report.cost_by_model == {}


# --- Weekly report ---


class TestWeeklyReport:
    def test_weekly_report_returns_7_days(self, project_with_fixtures):
        parser = ClaudeLogParser(logs_dir=project_with_fixtures)
        # Nota: esto usa date.today() internamente, así que los resultados
        # dependen del día de ejecución. Solo verificamos la estructura.
        weekly = parser.get_weekly_report()
        assert len(weekly) == 7
        # Deben estar ordenados de más antiguo a más reciente
        for i in range(len(weekly) - 1):
            assert weekly[i].date < weekly[i + 1].date


class TestWindowBoundaries:
    """Tests para el cálculo de ventana de 5h."""

    def test_basic_window(self):
        anchor = datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 4, 9, 12, 30, tzinfo=timezone.utc)
        start, end = ClaudeLogParser._compute_window_boundaries(anchor, 5, _now=now)
        assert start == datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)

    def test_window_crosses_day_boundary(self):
        anchor = datetime(2026, 4, 9, 22, 0, tzinfo=timezone.utc)
        now = datetime(2026, 4, 10, 1, 0, tzinfo=timezone.utc)
        start, end = ClaudeLogParser._compute_window_boundaries(anchor, 5, _now=now)
        assert start == datetime(2026, 4, 9, 22, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 10, 3, 0, tzinfo=timezone.utc)

    def test_window_several_cycles_later(self):
        anchor = datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc)
        # 8 días y 3.5h = 195.5h → 39 ciclos completos, dentro de ventana 39
        now = datetime(2026, 4, 9, 10, 30, tzinfo=timezone.utc)
        start, end = ClaudeLogParser._compute_window_boundaries(anchor, 5, _now=now)
        # Ventana 39: anchor + 39*5h = anchor + 195h = 2026-04-09T10:00
        assert start == datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)

    def test_exactly_at_boundary(self):
        anchor = datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)
        start, end = ClaudeLogParser._compute_window_boundaries(anchor, 5, _now=now)
        # En la frontera exacta, comienza la nueva ventana
        assert start == datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 9, 20, 0, tzinfo=timezone.utc)

    def test_custom_window_hours(self):
        anchor = datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 4, 9, 13, 30, tzinfo=timezone.utc)
        start, end = ClaudeLogParser._compute_window_boundaries(anchor, 3, _now=now)
        assert start == datetime(2026, 4, 9, 13, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 9, 16, 0, tzinfo=timezone.utc)

    def test_anchor_in_future_wraps_back(self):
        """Si el anchor es futuro, calcula hacia atrás."""
        anchor = datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        start, end = ClaudeLogParser._compute_window_boundaries(anchor, 5, _now=now)
        # -22h / 5h = -4.4 → floor = -5 → anchor - 25h = 04-09 09:00
        assert start == datetime(2026, 4, 9, 9, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 9, 14, 0, tzinfo=timezone.utc)


class TestEstimateNextReset:
    def test_returns_end_of_current_window(self):
        anchor = datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 4, 9, 12, 30, tzinfo=timezone.utc)
        reset = ClaudeLogParser._estimate_next_reset(anchor, 5, _now=now)
        assert reset == datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc)

    def test_no_anchor_returns_none(self):
        reset = ClaudeLogParser._estimate_next_reset(None, 5)
        assert reset is None


class TestGetWindowReport:
    """get_window_report solo cuenta tokens dentro de la ventana."""

    @staticmethod
    def _entry(msg_id, ts, inp=1000, out=500):
        return json.dumps({
            "type": "assistant",
            "timestamp": ts,
            "message": {
                "id": msg_id, "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": inp, "output_tokens": out,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        })

    def test_only_includes_entries_in_window(self, tmp_path):
        project = tmp_path / "-Users-test-proj"
        project.mkdir()
        session = project / "sess.jsonl"
        lines = [
            self._entry("m1", "2026-04-09T08:00:00.000Z"),  # dentro 07-12
            self._entry("m2", "2026-04-09T11:00:00.000Z"),  # dentro
            self._entry("m3", "2026-04-09T06:00:00.000Z"),  # fuera (antes)
            self._entry("m4", "2026-04-09T13:00:00.000Z"),  # fuera (después)
        ]
        session.write_text("\n".join(lines) + "\n")

        parser = ClaudeLogParser(logs_dir=tmp_path)
        window_start = datetime(2026, 4, 9, 7, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        report = parser.get_window_report(window_start, window_end)

        assert report.entry_count == 2
        total_eff = sum(report.effective_tokens_by_model.values())
        assert total_eff == 2 * (1000 + 500)

    def test_empty_window_returns_zero(self, tmp_path):
        parser = ClaudeLogParser(logs_dir=tmp_path)
        window_start = datetime(2026, 4, 9, 7, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        report = parser.get_window_report(window_start, window_end)
        assert report.entry_count == 0
        assert report.total_cost == 0.0

    def test_window_end_is_exclusive(self, tmp_path):
        project = tmp_path / "-Users-test-proj"
        project.mkdir()
        session = project / "sess.jsonl"
        lines = [
            self._entry("m1", "2026-04-09T12:00:00.000Z"),  # exactamente en window_end
        ]
        session.write_text("\n".join(lines) + "\n")

        parser = ClaudeLogParser(logs_dir=tmp_path)
        window_start = datetime(2026, 4, 9, 7, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        report = parser.get_window_report(window_start, window_end)
        assert report.entry_count == 0  # excluido

    def test_deduplication_within_window(self, tmp_path):
        project = tmp_path / "-Users-test-proj"
        project.mkdir()
        session = project / "sess.jsonl"
        lines = [
            self._entry("m1", "2026-04-09T08:00:00.000Z", inp=100, out=50),
            self._entry("m1", "2026-04-09T08:01:00.000Z", inp=200, out=100),  # same id
        ]
        session.write_text("\n".join(lines) + "\n")

        parser = ClaudeLogParser(logs_dir=tmp_path)
        window_start = datetime(2026, 4, 9, 7, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        report = parser.get_window_report(window_start, window_end)
        assert report.entry_count == 1
        total_eff = sum(report.effective_tokens_by_model.values())
        assert total_eff == 300  # last wins: 200+100
