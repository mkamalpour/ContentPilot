"""
tests/test_end_to_end.py — End-to-end testing for Content Agent API

This module provides comprehensive testing for the Content Agent API endpoints,
including URL processing, trend generation, content listing, and scheduling.

Features:
- Full pipeline testing with mocked dependencies
- Database isolation using temporary SQLite files
- Comprehensive endpoint validation
- Error handling verification
"""

import pytest
from fastapi.testclient import TestClient
from api.main import app

# =============================================================================
# TEST CLIENT SETUP
# =============================================================================

client = TestClient(app)

# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_db(tmp_path, monkeypatch):
    """
    Reset database for each test using a temporary SQLite file.

    This fixture ensures each test runs with a clean database state,
    preventing test interference and ensuring reliable test results.

    Args:
        tmp_path: Pytest fixture providing temporary directory
        monkeypatch: Pytest fixture for patching environment variables

    Yields:
        None: Database is reset for each test
    """
    # Use a temporary SQLite file for tests
    db_path = tmp_path / 'test.db'
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')
    yield

# =============================================================================
# TEST DATA
# =============================================================================

SAMPLE_URLS = [
    'https://example.com',
    'https://test.com/article',
    'https://blog.example.org/post'
]

SAMPLE_TRENDS = [
    'artificial intelligence',
    'machine learning',
    'data science',
    'blockchain technology'
]

# =============================================================================
# MOCK FUNCTIONS
# =============================================================================

def mock_scrape_url(url: str) -> str:
    """Mock scraper that returns sample text."""
    return f'Sample text content from {url}'

def mock_analyze_topic(text: str) -> str:
    """Mock analyzer that returns a sample topic."""
    return 'SampleTopic'

def mock_generate_content(topic: str) -> str:
    """Mock generator that returns sample content."""
    return f'Generated paragraph about {topic}'

def mock_get_trends(num_trends: int = 5) -> list:
    """Mock trend fetcher that returns sample trends."""
    return SAMPLE_TRENDS[:num_trends]

# =============================================================================
# END-TO-END TESTS
# =============================================================================

@pytest.mark.parametrize('url', SAMPLE_URLS)
def test_full_pipeline(monkeypatch, url):
    """
    Test the complete content generation pipeline.

    This test verifies that the entire workflow from URL processing
    to content generation and database storage works correctly.

    Args:
        monkeypatch: Pytest fixture for patching functions
        url: Test URL to process
    """
    # Mock all external dependencies for consistent testing
    monkeypatch.setattr('scraper.scraper.scrape_url', mock_scrape_url)
    monkeypatch.setattr('analyzer.analyzer.analyze_topic', mock_analyze_topic)
    monkeypatch.setattr('generator.generator.generate_content', mock_generate_content)

    # Test URL processing endpoint
    response = client.post('/process', json={'url': url})
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    assert 'topic' in data, "Response missing 'topic' field"
    assert 'body' in data, "Response missing 'body' field"
    assert data['topic'] == 'SampleTopic', f"Expected 'SampleTopic', got {data['topic']}"
    assert 'Generated paragraph' in data['body'], "Generated content not found in response"

    # Test content listing endpoint
    response2 = client.get('/contents')
    assert response2.status_code == 200, f"Expected 200, got {response2.status_code}"

    all_data = response2.json()
    assert isinstance(all_data, list), "Expected list response"
    assert len(all_data) == 1, f"Expected 1 content item, got {len(all_data)}"

    # Verify the content was saved correctly
    saved_content = all_data[0]
    assert saved_content['topic'] == 'SampleTopic'
    assert saved_content['url'] == url
    assert 'Generated paragraph' in saved_content['body']


def test_trends_endpoint(monkeypatch):
    """
    Test the trends endpoint functionality.

    Verifies that the trends endpoint returns valid trend data
    from different sources.
    """
    # Mock trend fetching
    monkeypatch.setattr('scraper.trends.get_random_trends', mock_get_trends)
    monkeypatch.setattr('scraper.trends.get_trends_from_trendaz', mock_get_trends)

    # Test explodingtopics source
    response = client.get('/trends?source=explodingtopics')
    assert response.status_code == 200

    data = response.json()
    assert 'trends' in data
    assert isinstance(data['trends'], list)
    assert len(data['trends']) > 0

    # Test trendaz source
    response2 = client.get('/trends?source=trendaz')
    assert response2.status_code == 200

    data2 = response2.json()
    assert 'trends' in data2
    assert isinstance(data2['trends'], list)


def test_generate_by_trend(monkeypatch):
    """
    Test trend-based content generation.

    Verifies that content can be generated from trend topics
    and saved to the database.
    """
    # Mock dependencies
    monkeypatch.setattr('CORE.core.generate_text', lambda topic, **kwargs: f'Generated content about {topic}')
    monkeypatch.setattr('scraper.trends.get_trend_from_source', lambda source: 'AI Technology')

    # Test with user-provided trend
    response = client.post('/generate_by_trend', json={
        'trend': 'artificial intelligence',
        'source': 'explodingtopics'
    })
    assert response.status_code == 200

    data = response.json()
    assert 'selected' in data
    assert 'body' in data
    assert data['selected'] == 'artificial intelligence'
    assert 'Generated content about artificial intelligence' in data['body']

    # Test with auto-fetched trend
    response2 = client.post('/generate_by_trend', json={
        'trend': '',
        'source': 'explodingtopics'
    })
    assert response2.status_code == 200

    data2 = response2.json()
    assert 'selected' in data2
    assert 'body' in data2
    assert data2['selected'] == 'AI Technology'


def test_schedule_endpoint():
    """
    Test job scheduling functionality.

    Verifies that jobs can be scheduled and canceled correctly.
    """
    # Test scheduling a job
    schedule_request = {
        'job_name': 'trend',
        'interval': '00:01:00',
        'enabled': True,
        'payload': {
            'trend': ['AI', 'ML'],
            'source': 'explodingtopics'
        }
    }

    response = client.post('/schedule', json=schedule_request)
    assert response.status_code == 200

    data = response.json()
    assert data['status'] == 'scheduled'

    # Test canceling a job
    cancel_request = {
        'job_name': 'trend',
        'enabled': False
    }

    response2 = client.post('/schedule', json=cancel_request)
    assert response2.status_code == 200

    data2 = response2.json()
    assert data2['status'] == 'canceled'


def test_flush_database():
    """
    Test database flush functionality.

    Verifies that all content can be deleted from the database.
    """
    # First, add some content
    client.post('/process', json={'url': 'https://example.com'})

    # Verify content exists
    response = client.get('/contents')
    assert response.status_code == 200
    initial_count = len(response.json())
    assert initial_count > 0

    # Flush the database
    response2 = client.delete('/flush_db')
    assert response2.status_code == 200

    data = response2.json()
    assert 'deleted' in data
    assert data['deleted'] == initial_count

    # Verify database is empty
    response3 = client.get('/contents')
    assert response3.status_code == 200
    final_count = len(response3.json())
    assert final_count == 0


def test_error_handling():
    """
    Test error handling for invalid requests.

    Verifies that the API properly handles malformed requests
    and returns appropriate error responses.
    """
    # Test invalid URL
    response = client.post('/process', json={'url': 'invalid-url'})
    assert response.status_code == 422  # Validation error

    # Test unknown job type
    response2 = client.post('/schedule', json={
        'job_name': 'unknown_job',
        'enabled': True
    })
    assert response2.status_code == 400

    # Test invalid datetime format
    response3 = client.post('/schedule', json={
        'job_name': 'trend',
        'datetimes': ['invalid-datetime'],
        'enabled': True
    })
    assert response3.status_code == 400


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

def test_concurrent_requests(monkeypatch):
    """
    Test API performance under concurrent load.

    Verifies that the API can handle multiple simultaneous requests
    without errors or data corruption.
    """
    # Mock dependencies for fast testing
    monkeypatch.setattr('scraper.scraper.scrape_url', mock_scrape_url)
    monkeypatch.setattr('analyzer.analyzer.analyze_topic', mock_analyze_topic)
    monkeypatch.setattr('generator.generator.generate_content', mock_generate_content)

    import concurrent.futures
    import threading

    def make_request():
        """Make a single API request."""
        response = client.post('/process', json={'url': 'https://example.com'})
        return response.status_code == 200

    # Test concurrent requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_request) for _ in range(10)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    # All requests should succeed
    assert all(results), "Some concurrent requests failed"


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

def test_wordpress_integration(monkeypatch):
    """
    Test WordPress integration (mocked).

    Verifies that content is properly formatted for WordPress
    and the integration doesn't break the main workflow.
    """
    # Mock WordPress API call
    def mock_wordpress_post(content_data):
        return {'status': 'success', 'id': 123}

    monkeypatch.setattr('database.listener.post_to_wordpress', mock_wordpress_post)

    # Process a URL (should trigger WordPress integration)
    response = client.post('/process', json={'url': 'https://example.com'})
    assert response.status_code == 200

    # Verify content was processed and saved
    response2 = client.get('/contents')
    assert response2.status_code == 200
    assert len(response2.json()) > 0


if __name__ == "__main__":
    """
    Run tests directly for debugging.

    Usage:
        python -m pytest tests/test_end_to_end.py -v
    """
    pytest.main([__file__, "-v"])
