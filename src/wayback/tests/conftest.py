import pytest
from wayback import WaybackClient, WaybackSession
from wayback._utils import RateLimit


@pytest.fixture
def test_client():
    session = None
    with pytest.warns(DeprecationWarning, match='timemap_calls_per_second'):
        session = WaybackSession(
            search_calls_per_second=RateLimit(0),
            memento_calls_per_second=RateLimit(0),
            timemap_calls_per_second=RateLimit(0),
        )
    client = WaybackClient(session)
    yield client
    client.close()
