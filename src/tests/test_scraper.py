"""The scraper must never hang on a stalled connection, and must pause between recipes."""

import scraper_v2


class _Stop(Exception):
    pass


def test_recipe_request_has_a_timeout(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        raise _Stop

    monkeypatch.setattr(scraper_v2.requests, "get", fake_get)
    scraper_v2.scrape_allrecipes("https://www.allrecipes.com/recipe/1/x/")

    assert seen.get("timeout") == scraper_v2.REQUEST_TIMEOUT_SECONDS
    assert 0 < scraper_v2.REQUEST_TIMEOUT_SECONDS <= 60


def test_default_delay_between_requests_is_not_zero():
    assert scraper_v2.DELAY_BETWEEN_REQUESTS_SECONDS > 0


def test_user_agent_identifies_the_scraper_instead_of_posing_as_a_browser():
    assert "Mozilla" not in scraper_v2.USER_AGENT
    assert "ai-recipe" in scraper_v2.USER_AGENT


def test_both_requests_send_the_configured_user_agent(monkeypatch):
    seen = []

    def fake_get(url, **kwargs):
        seen.append(kwargs["headers"]["User-Agent"])
        raise _Stop

    monkeypatch.setattr(scraper_v2.requests, "get", fake_get)
    scraper_v2.scrape_allrecipes("https://www.allrecipes.com/recipe/1/x/")
    scraper_v2.scrape_sitemap_recipes(limit=1)

    assert len(seen) == 2, "expected one request from each function"
    assert all(ua == scraper_v2.USER_AGENT for ua in seen)
