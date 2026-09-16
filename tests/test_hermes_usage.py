import sqlite3
import unittest
from tools.agent_telemetry import hermes_usage

class HermesUsageTests(unittest.TestCase):
    def test_cached_input_auxiliary_calls_and_legacy_fallback_without_double_counting(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('create table sessions(id,parent_session_id,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,reasoning_tokens,started_at,last_activity_at)')
            db.execute('create table session_model_usage(session_id,task,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,reasoning_tokens,first_seen,last_seen)')
            db.execute("insert into sessions values('s',NULL,10,20,1000,5,15,100,200)")
            db.execute("insert into session_model_usage values('s','',10,20,1000,5,15,100,200)")
            db.execute("insert into session_model_usage values('s','background_review',2,3,50,0,2,110,210)")
            db.execute("insert into sessions values('legacy',NULL,1,2,30,0,1,150,200)")
            month,lower,session=hermes_usage(db,50,'s')
            self.assertEqual(session,1090)
            self.assertEqual(month,1123)
            self.assertFalse(lower)

    def test_boundary_spanning_ledger_is_labeled_lower_bound(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('create table sessions(id,parent_session_id,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,started_at,last_activity_at)')
            db.execute('create table session_model_usage(session_id,task,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,first_seen,last_seen)')
            db.execute("insert into session_model_usage values('s','',10,20,1000,0,10,200)")
            self.assertEqual(hermes_usage(db,100,'s'),(0,True,1030))
