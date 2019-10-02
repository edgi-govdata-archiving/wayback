from datetime import datetime
import queue
import threading
from web_monitoring.utils import extract_title, rate_limited, FiniteQueue


def test_extract_title():
    title = extract_title(b'''<html>
        <head><title>THIS IS THE TITLE</title></head>
        <body>Blah</body>
    </html>''')
    assert title == 'THIS IS THE TITLE'


def test_extract_title_from_titleless_page():
    title = extract_title(b'''<html>
        <head><meta charset="utf-8"></head>
        <body>Blah</body>
    </html>''')
    assert title == ''


def test_extract_title_handles_whitespace():
    title = extract_title(b'''<html>
        <head>
            <meta charset="utf-8">
            <title>

                THIS IS
                THE  TITLE
            </title>
        </head>
        <body>Blah</body>
    </html>''')
    assert title == 'THIS IS THE TITLE'


def test_rate_limited():
    start_time = datetime.utcnow()
    for i in range(2):
        with rate_limited(calls_per_second=2):
            1 + 1
    duration = datetime.utcnow() - start_time
    assert duration.total_seconds() > 0.5


def test_separate_rate_limited_groups_do_not_affect_each_other():
    start_time = datetime.utcnow()

    with rate_limited(calls_per_second=2, group='a'):
        1 + 1
    with rate_limited(calls_per_second=2, group='b'):
        1 + 1
    with rate_limited(calls_per_second=2, group='a'):
        1 + 1
    with rate_limited(calls_per_second=2, group='b'):
        1 + 1

    duration = datetime.utcnow() - start_time
    assert duration.total_seconds() > 0.5
    assert duration.total_seconds() < 0.55


class TestFiniteQueue:
    def test_queue_ends_with_QUEUE_END(self):
        test_queue = FiniteQueue()
        test_queue.put('First')
        test_queue.end()

        assert test_queue.get() == 'First'
        assert test_queue.get() is FiniteQueue.QUEUE_END
        # We should keep getting QUEUE_END from now on, too.
        assert test_queue.get() is FiniteQueue.QUEUE_END

    def test_queue_is_iterable(self):
        test_queue = FiniteQueue()
        test_queue.put('First')
        test_queue.end()

        result = list(test_queue)
        assert result == ['First']

    def test_queue_can_be_safely_read_from_multiple_threads(self):
        # We want to make sure that a thread can't get stuck waiting for the
        # next item on a queue that is already ended.
        test_queue = FiniteQueue()
        results = queue.SimpleQueue()

        def read_one_item():
            try:
                results.put(test_queue.get(timeout=1))
            except queue.Empty as error:
                results.put(error)

        threads = [threading.Thread(target=read_one_item) for i in range(3)]
        [thread.start() for thread in threads]
        test_queue.put('First')
        test_queue.end()
        [thread.join() for thread in threads]

        assert results.get() == 'First'
        assert results.get() is FiniteQueue.QUEUE_END
        assert results.get() is FiniteQueue.QUEUE_END
