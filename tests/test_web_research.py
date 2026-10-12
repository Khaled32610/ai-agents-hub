from unittest.mock import patch

from web_research.browser_agent import PageContent
from web_research.report_exporter import build_markdown_report, _render_html
from web_research.summarizer_agent import ArticleSummary, summarize_multiple


def test_report_includes_sources_without_llm_call():
    summaries = [ArticleSummary('https://example.com', 'Synthetic source', 'Summary')]
    report = build_markdown_report('Synthetic topic', summaries, report_body='Synthetic report')
    assert 'https://example.com' in report
    assert 'Synthetic report' in report


@patch('web_research.summarizer_agent.generate_text')
def test_failed_fetch_is_skipped(generate):
    assert summarize_multiple([PageContent('https://example.com', '', '', 'timeout')]) == []
    generate.assert_not_called()


@patch('web_research.summarizer_agent.generate_text', return_value='Summary')
def test_valid_content_is_summarized(generate):
    result = summarize_multiple([PageContent('https://example.com', 'Title', 'Synthetic text. ' * 50)], target_language='en')
    assert result[0].summary == 'Summary'
    generate.assert_called_once()


def test_html_escapes_untrusted_content_and_rejects_script_links():
    html = _render_html('<script>alert(1)</script>', [ArticleSummary('javascript:alert(1)', '<img src=x>', 'x')], report_body='<img src=x onerror=alert(1)>')
    assert '<script>' not in html
    assert '<img' not in html
    assert 'href="javascript:' not in html
    assert '&lt;img' in html
