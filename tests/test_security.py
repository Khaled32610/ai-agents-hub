import socket
from unittest.mock import patch, MagicMock
import pytest

from shared.url_safety import require_public_url
from shared.ocr_utils import _normalize_digits, extract_text_from_pdf
from invoice_extraction.sheets_writer import append_invoice_row
from invoice_extraction.validation_agent import validate_invoice
from tests.test_invoice_extraction import make_invoice


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://user:pass@example.com', 'javascript:alert(1)'])
def test_unsafe_url_schemes_and_credentials(url):
    with pytest.raises(ValueError):
        require_public_url(url)


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1'])
def test_private_browser_destinations(address):
    with patch('shared.url_safety.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 80))]):
        with pytest.raises(ValueError):
            require_public_url('http://example.com')


def test_public_browser_destination():
    with patch('shared.url_safety.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]):
        require_public_url('https://example.com')


def test_digit_normalization():
    assert _normalize_digits('١٢٣ ۴۵۶') == '123 456'


def test_synthetic_pdf_text_extraction(tmp_path):
    import pymupdf
    path = tmp_path / 'sample.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), 'Synthetic invoice INV-001 total 114 EGP. No customer data.')
        doc.save(path)
    result = extract_text_from_pdf(path)
    assert result.engine == 'pymupdf'
    assert 'INV-001' in result.text


def test_sheets_uses_raw_cells_for_untrusted_vendor():
    service = MagicMock()
    invoice = make_invoice(vendor_name='=IMPORTXML("https://example.com", "//x")')
    with patch('invoice_extraction.sheets_writer._get_service', return_value=service), patch('invoice_extraction.sheets_writer.ensure_headers'):
        append_invoice_row('synthetic-id', None, 'sample.pdf', invoice, validate_invoice(invoice))
    arguments = service.spreadsheets().values().append.call_args.kwargs
    assert arguments['valueInputOption'] == 'RAW'
    assert arguments['body']['values'][0][3] == invoice.vendor_name


def test_pdf_renderer_blocks_external_resources(tmp_path):
    from web_research.report_exporter import convert_markdown_to_pdf
    path = tmp_path / 'sample.md'
    path.write_text('# Synthetic report\n\n![image](file:///etc/passwd)')
    with patch('weasyprint.HTML') as renderer:
        convert_markdown_to_pdf(path, target_language='en')
    fetch = renderer.call_args.kwargs['url_fetcher']
    for url in ['file:///etc/passwd', 'http://127.0.0.1', 'https://example.com/image.png']:
        with pytest.raises(ValueError):
            fetch(url)
