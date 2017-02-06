/*
 * Copyright (c) 2017 Allan Pichardo.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

/// <reference path="../../node_modules/@types/jquery/index.d.ts" />

export interface PagefreezerResponse {
    status: string;
    result: Result;
}

export interface Result {
    status: string;
    output: Output;
}

export interface Output {
    html: string;
    diffs: Diff;
    rawHtml2: string;
    rawHtml1: string;
}

export interface Diff {

    new: string;
    old: string;
    change: number;
    offset: number;
}

export class Pagefreezer {

    public static DIFF_API_URL = "/diff";
    public static API_KEY = "SP949Hsfdm2z9rYbnb9mC588hO2uV3Nna2pcy1cj";

    public static diffPages(url1: string, url2: string, callback: (response: PagefreezerResponse, status: string) => void) {

        $.ajax({
            type: "GET",
            url: Pagefreezer.DIFF_API_URL,
            dataType: "json",
            jsonpCallback: callback,
            data: {
                old_url: url1,
                new_url: url2,
                as: "json",
            },
            success: callback,
            error: function(error) {
                console.log(error);
            },
            headers: {"x-api-key": "SP949Hsfdm2z9rYbnb9mC588hO2uV3Nna2pcy1cj"}
        });

    }

}