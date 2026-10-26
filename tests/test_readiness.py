import json
from fastapi.testclient import TestClient
from api import main
from core import config


def test_health_reports_missing_configuration_without_provider_calls_or_secrets(monkeypatch):
    monkeypatch.setattr(config, 'MODEL_PROVIDER', 'hf')
    monkeypatch.setattr(config, 'HF_TOKEN', '')
    with TestClient(main.app) as client:
        report = client.get('/health').json()['readiness']
        assert not report['configuration_complete'] and report['model_health'] == 'not_checked'
        monkeypatch.setattr(config, 'HF_TOKEN', 'synthetic-test-credential')
        ready = client.get('/health').json()['readiness']
    assert ready['configuration_complete']
    assert 'synthetic-test-credential' not in json.dumps(ready)


def test_invalid_local_endpoint_is_actionable(monkeypatch):
    from core.llm import configuration_readiness
    monkeypatch.setattr(config, 'MODEL_PROVIDER', 'local')
    monkeypatch.setattr(config, 'LMSTUDIO_API_BASE', 'not-an-endpoint')
    report = configuration_readiness()
    assert not report['configuration_complete']
    assert any(row['check'] == 'local_endpoint' and not row['ok'] for row in report['checks'])
