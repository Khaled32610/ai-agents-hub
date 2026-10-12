from unittest.mock import patch

from fastapi.testclient import TestClient
import api
from tests.test_invoice_extraction import make_invoice
from shared.ocr_utils import ExtractedDocument

client = TestClient(api.app)


def test_health():
    assert client.get('/health').json() == {'status': 'ok'}


def test_research_rejects_unbounded_inputs():
    for payload in [{'query': ''}, {'query': '  '}, {'query': 'Example', 'max_results': 0}, {'query': 'Example', 'max_results': 100}, {'query': 'Example', 'export_format': 'exe'}]:
        assert client.post('/research/run', json=payload).status_code == 422


def test_upload_rejects_unsupported_file():
    assert client.post('/invoices/process', files={'file': ('sample.exe', b'fake')}).status_code == 415


def test_duplicate_invoice_short_circuits():
    with patch('api.is_duplicate', return_value=True), patch('api.extract_invoice_data') as extract:
        response = client.post('/invoices/process', files={'file': ('sample.pdf', b'synthetic')})
    assert response.status_code == 200
    assert response.json()['duplicate'] is True
    extract.assert_not_called()


def test_invoice_pipeline_with_mocked_services():
    with patch('api.is_duplicate', return_value=False), patch('api.process_invoice_file', return_value=ExtractedDocument('Synthetic', 'pymupdf', 1, 'hash')), patch('api.extract_invoice_data', return_value=make_invoice()), patch('api.append_invoice_row') as sheets, patch('api.save_invoice_record') as database:
        response = client.post('/invoices/process', files={'file': ('sample.pdf', b'synthetic')})
    assert response.status_code == 200
    assert response.json()['is_valid'] is True
    sheets.assert_called_once()
    database.assert_called_once()


def test_download_rejects_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / 'reports'
    root.mkdir()
    private = tmp_path / 'private.txt'
    private.write_text('synthetic private content')
    (root / 'escape.md').symlink_to(private)
    monkeypatch.setattr(api, 'REPORTS_DIR', root)
    assert client.get('/research/report', params={'path': 'escape.md'}).status_code == 400
