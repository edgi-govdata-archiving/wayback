comes with dockerfile (just docker build -t yay . ; docker run -t yay)

then POST localhost:8000 with 
{
    "rawHtml": "someRawHtml"
}

and you'll get
{
    "articleText": "hopefully just the text of the article and not the text of the menus and junk",
    "rawHtml": "what you imput"
}