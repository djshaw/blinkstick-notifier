import json
import os
from typing import List
from unittest import TestCase
from parameterized import parameterized

import jsonschema

def get_tests_samples() -> List[str]:
    results = []
    for directory in os.listdir(os.path.dirname(__file__)):
        if not os.path.isdir( os.path.join( os.path.dirname(__file__), directory ) ):
            continue

        if directory == '__pycache__':
            continue

        schema_filename = f"{directory}.schema.json"
        schema = get_schema_file(schema_filename)
        for test in os.listdir(os.path.join(os.path.dirname(__file__), directory)):
            test_filename = test
            results.append([schema_filename,
                            schema,
                            test_filename,
                            get_json_file(os.path.join(os.path.dirname(__file__), directory, test_filename))])

    return results

def custom_name_func(testcase, param_num, param):
    return ("test_" + param[0][0] + "/" + param[0][2]).replace(".", "_")

def get_schema_file(file) -> object:
    return get_json_file(os.path.join(os.path.dirname(__file__), '..', '..', 'src', file))

def get_json_file(file: str) -> object:
    with open(file, 'r', encoding='ascii') as f:
        return json.loads(f.read())

class SchemaTest(TestCase):
    @parameterized.expand(get_tests_samples(), name_func=custom_name_func)
    def test_schema(self, scehma_filename: str, schema: dict, message_filename: str, message: dict) -> None:
        jsonschema.validate(schema=schema, instance=message)
