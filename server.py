#! /usr/bin/env python3
# -*- coding: utf-8 -*-

from calendar import timegm
from datetime import datetime
from flask import Flask, request, jsonify
import re
import _strptime  # https://bugs.python.org/issue7980
import subprocess
import sys

app = Flask(__name__)
app.debug = True

ledgerfile = None
SPLITTER = "|"

@app.route("/")
def health_check():
    return "ok"

@app.route('/search', methods=['POST'])
def search():
    accounts = __get_account_names()
    return jsonify(accounts)

@app.route('/query', methods=['POST'])
def query():
    req = request.get_json()

    from_ = __convert_to_date(req['range']['from'])
    to = __convert_to_date(req['range']['to'])

    print(req, from_, to)

    data = []
    for target in req['targets']:
        target_name = target['target']
        balance = __balance(from_, to, target_name)
        ts = __convert_to_time_ms(req['range']['from'])
        data.append(
            {
                "target": target['target'],
                "datapoints":
                [
                    [balance, ts]
                ]
            })

    return jsonify(data)

@app.route('/annotations', methods=['POST'])
def annotations():
    req = request.get_json()
    print(req)
    data = [
        {
            "annotation": 'This is the annotation',
            "time": (convert_to_time_ms(req['range']['from']) +
                     convert_to_time_ms(req['range']['to'])) / 2,
            "title": 'Deployment notes',
            "tags": ['tag1', 'tag2'],
            "text": 'Hm, something went wrong...'
        }
    ]
    return jsonify(data)

@app.after_request
def after_request(response):
    # CORS headers
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

def __convert_to_date(timestamp):
    parsed_timestamp = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    return parsed_timestamp.strftime("%Y-%m-%d")

def __convert_to_time_ms(timestamp):
    return 1000 * timegm(datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ').timetuple())

def __get_account_names():
    accounts_raw = subprocess.check_output([
        "ledger",
        "-f", ledgerfile,
        "accounts"
    ]).decode("utf-8")

    account_flat_list = accounts_raw.split('\n')
    account_hierarchy_list = [__extract_hierarchical_account_names(account) for account in account_flat_list]
    unique_accounts = set(__flatten_list(account_hierarchy_list))
    return sorted(list(unique_accounts))

def __balance(from_, to, account_name):
    command = [
            "ledger",
            "-f", ledgerfile,
            "balance",
            "--no-total",
            "--format",
            "%(total)" + SPLITTER,
            "--begin", from_,
            "--end", to,
            "'^" + account_name + "'"
        ]
    expense_raw = subprocess.check_output(command).decode("utf-8")
    print("raw", command, expense_raw)
    return __parse_total(expense_raw)

def __parse_total(raw):
    stripped_raw = raw.strip('"').strip()
    if not stripped_raw:
        return 0

    # we are parsing only the top entry
    splitter_index = stripped_raw.index(SPLITTER)
    if splitter_index == -1:
        return 0
    else:
        raw_amounts = stripped_raw[:splitter_index].split("\n")
        return __parse_amount(raw_amounts)

def __parse_amount(raw_amounts):
    amount = 0.0
    for raw_amount in raw_amounts:
        raw_amount = raw_amount.replace(',', '')
        if "$" in raw_amount:
            amount += float(raw_amount.strip("$"))
        elif "INR" in raw_amount:
            # hack
            amount += float(raw_amount.strip("INR")) / 70
        elif "{" in raw_amount:
            # commodity
            commodity_amount = re.search(".*{(.*)}.*", raw_amount).group(1)
            amount += __parse_amount(commodity_amount)
        else:
            raise ("Cannot parse ", raw_amount)
    return amount

# Expenses:Grocery:Vegetables -> [Expenses, Expenses:Grocery, Expenses:Grocery:Vegetables]
def __extract_hierarchical_account_names(hierarchy_name):
    if not hierarchy_name:
        return []

    last_colon_index = hierarchy_name.rfind(":")
    if last_colon_index > -1:
        result = __extract_hierarchical_account_names(hierarchy_name[:last_colon_index])
        result.append(hierarchy_name)
        return result
    else:
        return [hierarchy_name]

def __flatten_list(list_of_lists):
    # https://stackoverflow.com/a/11264751
    return [val for sublist in list_of_lists for val in sublist]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python app.py <ledgerfile location>")
        exit(1)
    ledgerfile = sys.argv[1]
    print("Using ledger file: ", ledgerfile)
    app.run()
