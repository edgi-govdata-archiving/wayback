from flask import Flask, render_template, request, jsonify
from newspaper import Article
app = Flask(__name__)


def get_article_text(raw_html):
    a = Article('FAKE_URL')
    a.set_html(raw_html)
    a.parse()
    return a.text


@app.route("/get_article_text", methods=["POST"])
def data():
    raw_html = request.get_json()['rawHtml']
    return jsonify({
        "rawHtml": raw_html,
        "articleText": get_article_text(raw_html)
    })


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000, debug=True)
