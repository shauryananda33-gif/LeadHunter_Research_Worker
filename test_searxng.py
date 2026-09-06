from serp_worker.searxng import SearXNGClient


def test_url_normalization():
    assert SearXNGClient._normalize_url("https://example.com/#x") == "https://example.com/"


def test_domain_blocking():
    assert SearXNGClient._blocked("www.google.com")
    assert not SearXNGClient._blocked("example.com")


def test_parse_results():
    client = SearXNGClient()
    results = client._parse(
        {"results": [
            {"title": "Example", "url": "https://example.com/a", "content": "A"},
            {"title": "Google", "url": "https://google.com/x", "content": "B"},
        ]},
        10,
    )
    assert len(results) == 1
    assert results[0].domain == "example.com"
