# Pagefreezer API

Pagefreezer provides a simple diff API that allows coparisons of file versions; results are returned as JSON in a straightforward way. At present only single-page comparisons are possible; we should determine whether it's worthwhile to use the service as currently constructed. 

## The Compare Service

This is the only service currently available; it allows comparison between two URL's or 2 html blobs (but not one of each). 

### Parameters


| Parameter	| Description |
|-----------|-------------|
| `source` (optional)|	Default: `url`. <br>`url`=url1 and url2 must be URL of the target document. <br>`text`=url1 and url2 contains HTML text document itself. |
| `url1` |	The source URL or HTML |
| `url2` |	The target URL or HTML |
| `diffmode` | (optional)	Default: `0`. <br>`0`=No pre-processing, <br>`1`=extra white spaces removed, <br>`2`=[\s]* are removed,<br>`3`=HTML tags are removed for full-text comparison |
| `html`  (optional) |	Default: `1`. <br>`2`=HTML with HEAD, <br>`1`=HTML without HEAD, <br>`0`=False (no HTML output). |
| `snippet`  (optional)	 | Default: `200` (characters). It will generate snippets of changes. |


### Examples

#### Using [httpie](https://github.com/jkbrzt/httpie)

```sh
http post https://api1.pagefreezer.com/v1/api/utils/diff/compare \
source=text \
url1="<h1>good news</h1>" \
url2="<h1>bad news</h1>" \
"x-api-key: KEYHERE"
```

#### Using curl
```sh

curl -v -H "Accept: application/json" \
        -H "Content-Type: application/json" \
        -H "x-api-key: SP949Hsfdm2z9rYbnb9mC588hO2uV3Nna2pcy1cj" \
        -X POST -d @./input.json \
        https://api1.pagefreezer.com/v1/api/utils/diff/compare
```
This example expects a file `input.json`:
```json
{"url1":"http://apple.com/jp", "url2":"http://apple.com/kr"}
```


### Using jQuery:
```javascript
$.ajax({
  type: "POST",
  url: "https://api1.pagefreezer.com/v1/api/utils/diff/compare",
  data: {
    url1: "<h1>good news</h1>" 
    url2: "<h1>bad news</h1>"
    source: "text",
    dataType: "json"
  },
  headers: {"x-api-key": "KEYHERE"}
});
 
```

## Testing
se the files in [archives](./archives) to test out the diff service
