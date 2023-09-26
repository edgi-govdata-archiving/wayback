from vcr import VCR
import vcr.serializers.yamlserializer
import zlib
import re
import urllib3
from pathlib import Path


CONTENT_TYPE_CHARSET_PATTERN = re.compile(r'(?:^|\s|;)charset=([^;]+)', re.I)
HTML_CHARSET_PATTERN = re.compile(r'<meta charset=([^\s>]+)', re.I)


def _get_header(response, key, default=None):
    """Get the values for a given header name on a VCR response dictionary."""
    return (response['headers'].get(key) or
            response['headers'].get(key.lower()) or
            default)


def _has_gzip_header(response):
    """Determine whether a response had a gzip content-encoding header."""
    return 'gzip' in _get_header(response, 'Content-Encoding', [])


def _is_gzip_bytes(raw_bytes):
    """Check whether some bytes might be gzip data."""
    return isinstance(raw_bytes, bytes) and raw_bytes.startswith(b'\x1f\x8b')


def _guess_encoding(response):
    """
    Try to guess the original text encoding of a VCR response dictionary.
    Since we no longer have access to the original bytes at this point, it's a
    best-effort proposition based on headers and hints in the content.

    This is loosely based on the requests package, with some additions and
    lazier parsing:
    https://github.com/psf/requests/blob/ee93fac6b2f715151f1aa9a1a06ddba9f7dcc59a/src/requests/utils.py#L534-L556
    """
    content_type = _get_header(response, 'Content-Type', [None])[0]
    if not content_type:
        return 'utf-8'

    content_type, _, parameters = content_type.partition(';')
    encoding_match = CONTENT_TYPE_CHARSET_PATTERN.search(parameters)
    if encoding_match:
        return encoding_match.group(1).strip('"\'')

    if 'html' in content_type:
        encoding_match = HTML_CHARSET_PATTERN.search(response['body']['string'])
        if encoding_match:
            return encoding_match.group(1).strip('"\'')

    if 'text' in content_type:
        return 'ISO-8859-1'

    if 'application/json' in content_type:
        return 'utf-8'


class Urllib3Serializer:
    """
    VCR serializes the responses for urllib3 v1 and v2 differently, which makes
    it a real pain to record and manage VCR cassettes. This serializer attempts
    to make cassettes compatible between both major versions of urllib3. It
    wraps another serializer (e.g. the default YAML serializer in VCR) that is
    responsible for writing the actual data.

    Specifically, it compresses and decompresses response bodies that were
    delivered as gzips. In urllib3 v1, it does nothing (since VCR is able to
    get and use the raw body bytes), but in urllib3 v2 it checks the headers to
    see if the response was compressed and recompresses it when serializing or
    decompresses it when deserializing (since VCR only sees decompressed bodies
    in urllib3 v2). For more info on this issue, see:
    https://github.com/kevin1024/vcrpy/issues/719
    """

    def __init__(self, base_serializer):
        self.base_serializer = base_serializer
        self.urllib3_version = int(urllib3.__version__.split('.', 1)[0])

    def deserialize(self, cassette_string):
        result = self.base_serializer.deserialize(cassette_string)

        if self.urllib3_version == 2 and result.get('version') == 1:
            for interaction in result['interactions']:
                response = interaction['response']
                raw_body = response['body'].get('string')
                if _has_gzip_header(response) and _is_gzip_bytes(raw_body):
                    response['body']['string'] = zlib.decompress(
                        raw_body,
                        wbits=zlib.MAX_WBITS | 16
                    )

        return result

    def serialize(self, cassette_dict):
        if self.urllib3_version == 2 and cassette_dict.get('version') == 1:
            for interaction in cassette_dict['interactions']:
                response = interaction['response']
                raw_body = response['body'].get('string')
                if (
                    _has_gzip_header(response) and
                    raw_body and
                    (not _is_gzip_bytes(raw_body))
                ):
                    if isinstance(raw_body, str):
                        encoding = _guess_encoding(response)
                        try:
                            raw_body = raw_body.encode(encoding)
                        except UnicodeEncodeError:
                            fallback = 'utf-8'
                            if encoding != fallback:
                                raw_body = raw_body.encode(fallback)
                            else:
                                raise

                    response['body']['string'] = zlib.compress(
                        raw_body,
                        level=9,
                        wbits=zlib.MAX_WBITS | 16
                    )

        return self.base_serializer.serialize(cassette_dict)


def create_vcr():
    custom_vcr = VCR(
        serializer='yaml',
        cassette_library_dir=str(Path(__file__).parent / Path('cassettes/')),
        path_transformer=VCR.ensure_suffix('.yaml'),
        record_mode='once',
        match_on=['uri', 'method'],
    )
    custom_vcr.register_serializer(
        'yaml',
        Urllib3Serializer(vcr.serializers.yamlserializer)
    )
    return custom_vcr
