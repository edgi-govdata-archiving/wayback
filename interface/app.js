/*
 * Copyright (c) 2017 Allan Pichardo.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */
"use strict"

let express = require('express');
let app = express();

app.set('views', __dirname + '/views');
app.use(express.static('dist'));
app.engine('html', require('ejs').renderFile);

/**
 * Main view for manual entry
 */
app.get('/', function (req, res) {
    res.render('main.html')
});

/**
 * Can return a pre-filled view
 * using a formatted query string
 * or just a json response
 *
 * parameters:
 * -old_url
 * -new_url
 * -as (optional) = view | json
 */
app.get('/diff?', function(req, res) {

    let oldUrl = req.query.old_url;
    let newUrl = req.query.new_url;
    let as = req.query.as;

    if(as != null && as == "view") {
        //render a view
        res.render('main.html', {
            'oldUrl' : oldUrl,
            'newUrl' : newUrl
        });
    } else {

        console.log('GETTING JSON');
        let querystring = require('querystring');
        let https = require('https');

        let postData = JSON.stringify({
            'source' : 'url',
            'url1' : oldUrl,
            'url2' : newUrl,
            'diff_mode' : 1
        });
        console.log(postData);
        let postOptions = {
            host: 'api1.pagefreezer.com',
            path: '/v1/api/utils/diff/compare',
            method: 'POST',
            port: 443,
            headers: {
                'Accept' : 'application/json',
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(postData),
                'x-api-key' : 'SP949Hsfdm2z9rYbnb9mC588hO2uV3Nna2pcy1cj'
            }
        };

        let postRequest = https.request(postOptions, function(response) {
            response.setEncoding('utf8');

            var body = '';

            response.on('data', function(chunk) {
                body += chunk;
            });

            response.on('end', function() {
                res.end(body);
                console.log(body);
            });
        });
        postRequest.write(postData);
        postRequest.end();
    }

});

app.listen(3000, function () {
    console.log('Listening on port 3000')
});