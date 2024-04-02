import unittest
from unittest import mock

from bitbucket_listener import BuildFailureManager
from myblinkstick.websocket_client import WebsocketClient

class BuildFailiureManagerTest(unittest.TestCase):
    def test_no_default_failures(self):
        """ When a BuildFailureManager is allocated, it doesn't start with any build failures """
        ws = mock.Mock(spec=WebsocketClient.__class__)
        manager = BuildFailureManager(ws, {})
        self.assertEqual(manager.get_failures(), {})


    def test_clear_failed_build_never_set__empty_config(self):
        """ Clearing a failed build that was never set as a failed build doesn't crash.  The
            repository isn't in the configuration. """
        ws = mock.Mock(spec=WebsocketClient.__class__)
        manager = BuildFailureManager(ws, {})
        repository = "repository"
        manager.clear_failed_build(repository)
        self.assertEqual(manager.get_failures(), {})


    def test_set_unset_failure(self):
        notification = "Notification"

        ws = mock.Mock(spec=WebsocketClient.__class__)
        ws.enable = mock.MagicMock(name='enable')

        repository = "Repository"
        config = {"notification": notification,
                  "pipelines": [repository]}
        uuid = "uuid"
        manager = BuildFailureManager(ws, config)
        manager.set_failed_build(repository, uuid)

        ws.enable.assert_called_once_with(notification)
        self.assertEqual(manager.get_failures(), {repository: uuid})


        ws.disable = mock.MagicMock(name='disable')
        manager.clear_failed_build(repository)

        ws.disable.assert_called_once_with(notification)
        self.assertEqual(manager.get_failures(), {})


    def test_overlap_set(self):
        """ Set failure 1, assert notification
            Set failure 2
            Clear failure 1
            Clear failure 2, assert notification removed """
        notification = "Notification"

        ws = mock.Mock(spec=WebsocketClient.__class__)
        ws.enable = mock.MagicMock(name='enable')

        repository1 = "Repository1"
        repository2 = "Repository2"
        config = {"notification": notification,
                  "pipelines": [repository1, repository2]}

        manager = BuildFailureManager(ws, config)

        uuid1 = "uuid1"
        manager.set_failed_build(repository1, uuid1)
        self.assertEqual(manager.get_failures(), {repository1: uuid1})
        ws.enable.assert_called_once_with(notification)

        uuid2 = "uuid2"
        manager.set_failed_build(repository2, uuid2)
        self.assertEqual(manager.get_failures(), {repository1: uuid1, repository2: uuid2})

        manager.clear_failed_build(repository1)
        self.assertEqual(manager.get_failures(), {repository2: uuid2})

        ws.disable = mock.MagicMock(name='disable')
        manager.clear_failed_build(repository2)
        self.assertEqual(manager.get_failures(), {})
        ws.disable.assert_called_once_with(notification)
