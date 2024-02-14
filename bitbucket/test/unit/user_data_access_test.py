import unittest
import json

from bitbucket_listener import UserDataAccess

class UserDataAccessTest( unittest.TestCase ):
    def test_user_data_access(self):
        user_json = None
        with open("/workspaces/blinkstick-notifier/bitbucket/test/unit/User.json", 'r', encoding='ascii') as f:
            user_json = json.load( f )

        user_data_access = UserDataAccess(user_json)
        self.assertEqual('jdoe_ws', user_data_access.get_username())
        self.assertEqual('{8d552f62-7bab-44bd-b43f-80ada2963466}', user_data_access.get_uuid())
