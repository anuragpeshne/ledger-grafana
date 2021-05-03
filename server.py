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
ELEMENT_SPLITTER = "|"
RECORD_SPLITTER = "\t"

ACCOUNT_QUERY_SPLITTER = " - "

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
        account_name, query_type = target['target'].split(ACCOUNT_QUERY_SPLITTER)
        parsed_records = __register(from_, to, account_name)

        if query_type == "amount":
            datapoints = [[amount, ts] for ts, amount, _ in parsed_records]
        else:
            datapoints = [[sum_, ts] for ts, _, sum_ in parsed_records]

        if not datapoints:
            datapoints = [[0, to.replace('-','/')]]
        datapoints = [[v, __convert_date_to_time_ms(ts)] for v, ts in datapoints]
        data.append(
            {
                "target": account_name,
                "datapoints": datapoints
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

def __convert_to_date(timestamp: str) -> str:
    parsed_timestamp = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    return parsed_timestamp.strftime("%Y-%m-%d")

def __convert_date_to_time_ms(timestamp: str) -> int:
    return 1000 * timegm(datetime.strptime(timestamp, '%Y/%m/%d').timetuple())

def __get_account_names() -> [str]:
    accounts_raw = subprocess.check_output([
        "ledger",
        "-f", ledgerfile,
        "accounts"
    ]).decode("utf-8")

    account_flat_list = accounts_raw.split('\n')
    account_hierarchy_list = [__extract_hierarchical_account_names(account) for account in account_flat_list]
    unique_accounts = set(__flatten_list(account_hierarchy_list))
    account_names = sorted(list(unique_accounts))

    query_types = ['amount', 'cumulative-sum']
    return [account + ACCOUNT_QUERY_SPLITTER + query for account in account_names for query in query_types]

def __parse_amount(raw_amounts: [float]) -> float:
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
        elif raw_amount == '0':
            pass
        else:
            print("cannot parse ", raw_amount)
            #raise Exception("Cannot parse ", raw_amount)
    return amount

# Expenses:Grocery:Vegetables -> [Expenses, Expenses:Grocery, Expenses:Grocery:Vegetables]
def __extract_hierarchical_account_names(hierarchy_name: str) -> [str]:
    if not hierarchy_name:
        return []

    last_colon_index = hierarchy_name.rfind(":")
    if last_colon_index > -1:
        result = __extract_hierarchical_account_names(hierarchy_name[:last_colon_index])
        result.append(hierarchy_name)
        return result
    else:
        return [hierarchy_name]

def __flatten_list(list_of_lists: [[str]]) -> [str]:
    # https://stackoverflow.com/a/11264751
    return [val for sublist in list_of_lists for val in sublist]

def __register(from_: str, to: str, account: str) -> [[int, float, float]]:
    command = [
        "ledger",
        "-f", ledgerfile,
        "register",
        "--no-total",
        "--flat",
        "--format",
        ELEMENT_SPLITTER.join(["%(date)", "%(account)", "%t", "%T" + RECORD_SPLITTER]),
        "--begin", from_,
        "--end", to,
        "'^" + account + "'"]
    expense_raw = subprocess.check_output(command).decode("utf-8")
    print(command, expense_raw)
    expense_processed = __parse_register(expense_raw)
    print(expense_processed)
    print('\n')
    return expense_processed

def __parse_register(raw: str) -> [[str, float, float]]:
    raw_records = raw.strip().split(RECORD_SPLITTER)
    parsed_records = []

    for raw_record in raw_records:
        if __is_empty(raw_record):
            continue
        date, account, amount, sum_ = raw_record.split(ELEMENT_SPLITTER)
        sum_ = sum_.split('\n')

        amount = __parse_amount([amount])
        sum_ = __parse_amount(sum_)
        parsed_records.append([date, amount, sum_])

    unique_timestamp_records = __merge_duplicate_timestamp_amount_sum(parsed_records)
    return unique_timestamp_records

def __is_empty(string: str) -> bool:
    print(string.strip() == '')
    return string.strip() == ''

def __merge_duplicate_timestamp_amount_sum(records: [[str, float, float]]) -> [[str, float, float]]:
    map_ = {}
    for ts, amount, sum_ in records:
        if not ts in map_:
            map_[ts] = [amount, sum_]
        else:
            existing_amount, existing_sum = map_[ts]
            map_[ts] = [existing_amount + amount, max(existing_sum, sum_)]
    return [[key, map_[key][0], map_[key][1]] for key in map_]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python app.py <ledgerfile location>")
        exit(1)
    ledgerfile = sys.argv[1]
    print("Using ledger file: ", ledgerfile)
    app.run()
