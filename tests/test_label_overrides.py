import copy
import tempfile
import unittest
from pathlib import Path
from tools.label_overrides import LabelSync, read, merge, capture, apply


def profile(mode='shared'):
    titles=['Old']*3 if mode=='shared' else ['Desktop','Mic HOT','Muted']
    return {'keys':[{'action':{'uuid':'test'},'settings':{'_label_id':'stable-id','_label_defaults':titles.copy(),'_label_mode':mode},'states':[{'text':t} for t in titles],'current_state':2}]}

class LabelTests(unittest.TestCase):
    def test_edit_in_any_state_persists_and_sends_all_state_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'labels.json';events=[];sync=LabelSync(events.append,path)
            settings=profile()['keys'][0]['settings']
            sync.appear('context',settings)
            sync.changed('context',{'title':'Old'})
            self.assertFalse(path.exists())
            sync.changed('context',{'title':'Renamed','state':2})
            self.assertEqual(events,[{'event':'setTitle','context':'context','payload':{'title':'Renamed'}}])
            self.assertEqual(read(path)['labels']['stable-id'],{'shared':'Renamed'})
            sync.changed('context',{'title':'Renamed'})
            self.assertEqual(len(events),1)
            regenerated=profile();apply(regenerated,read(path)['labels'])
            self.assertEqual([s['text'] for s in regenerated['keys'][0]['states']],['Renamed']*3)
            sync.disappear('context');sync.appear('context',settings)
            sync.changed('context',{'title':'Old'})
            self.assertEqual(read(path)['labels']['stable-id']['shared'],'Renamed')

    def test_blank_label_is_a_real_override(self):
        edited=profile();edited['keys'][0]['states'][1]['text']=''
        overrides=capture(edited);fresh=profile();apply(fresh,overrides)
        self.assertEqual([s['text'] for s in fresh['keys'][0]['states']],['']*3)

    def test_per_state_audio_labels_stay_independent(self):
        edited=profile('per_state');edited['keys'][0]['states'][1]['text']='LIVE'
        overrides=capture(edited);fresh=profile('per_state');apply(fresh,overrides)
        self.assertEqual([s['text'] for s in fresh['keys'][0]['states']],['Desktop','LIVE','Muted'])
        with tempfile.TemporaryDirectory() as directory:
            events=[];sync=LabelSync(events.append,Path(directory)/'labels.json')
            sync.appear('audio',edited['keys'][0]['settings']);sync.changed('audio',{'title':'Muted'})
            sync.changed('audio',{'title':'LIVE'})
            self.assertEqual(events,[])

    def test_import_legacy_app_edit_before_install(self):
        fresh=profile();installed=copy.deepcopy(fresh);installed['keys'][0]['settings']={}
        installed['keys'][0]['states'][0]['text']='App edit'
        overrides=capture(installed,fresh);apply(fresh,overrides)
        self.assertEqual([s['text'] for s in fresh['keys'][0]['states']],['App edit']*3)

    def test_merge_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'labels.json';merge({'one':{'shared':'First'}},path);merge({'two':{'shared':'Second'}},path)
            self.assertEqual(set(read(path)['labels']),{'one','two'})

    def test_keys_that_write_their_own_titles_never_become_user_overrides(self):
        # A battle key's title comes from the plugin, so an app-reported change to
        # it is not a user edit and must not be pinned in the override file.
        dynamic = {'keys':[{'action':{'uuid':'test'},
                            'settings':{'_label_id':'f1-battle/0','_label_defaults':['','',''],'_label_mode':'shared',
                                        'kind':'f1_battle'},
                            'states':[{'text':''}]*3,'current_state':0}]}
        self.assertEqual(capture(dynamic), {})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'labels.json';events=[];sync=LabelSync(events.append,path)
            sync.appear('battle',dynamic['keys'][0]['settings'])
            sync.changed('battle',{'title':'VER'})
            sync.changed('battle',{'title':'','settings':dynamic['keys'][0]['settings']})
            self.assertFalse(path.exists())
            self.assertEqual(events,[])
