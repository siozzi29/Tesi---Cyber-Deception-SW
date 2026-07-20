import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import train
from features import extract_features


class TrainFeatureConsistencyTests(unittest.TestCase):
    def test_extract_features_from_row_matches_shared_extractor(self):
        row = {
            "URL": "/tienda1/publico/pagar.jsp?id=123&debug=1 HTTP/1.1",
            "Method": "GET",
            "content": "",
            "content-type": "application/x-www-form-urlencoded",
        }

        expected = extract_features(
            str(row["URL"]),
            str(row["Method"]),
            str(row["content"]),
            str(row["content-type"]),
        )
        actual = train.extract_features_from_row(row)

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
