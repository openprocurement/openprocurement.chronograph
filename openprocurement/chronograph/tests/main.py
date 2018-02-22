# -*- coding: utf-8 -*-

import unittest

from openprocurement.chronograph.tests import test, test_scheduler


def suite():
    tests = unittest.TestSuite()
    tests.addTest(test.suite())
    tests.addTest(test_scheduler.suite())
    return tests


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
