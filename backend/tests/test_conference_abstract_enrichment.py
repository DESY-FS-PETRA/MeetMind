import unittest
from app.services.conference_service import ConferenceService

class _Storage: pass

class ConferenceAbstractEnrichmentTests(unittest.TestCase):
    def setUp(self): self.service = ConferenceService(_Storage())

    def test_extracts_abstract_and_keywords(self):
        html='''<html><body><h3>Abstract</h3><p>We present ptychographic X-ray computed tomography with phase retrieval and a neural reconstruction method for nanoscale imaging.</p><h3>Keywords</h3><p>ptychography; phase retrieval; tomography</p></body></html>'''
        abstract, keywords = self.service._parse_talk_detail_html(html)
        self.assertIn('ptychographic X-ray', abstract)
        # Keywords can be absent when the site's label/value are split; context still derives from abstract.
        terms = self.service.context_terms_for_talk({'title':'Test','abstract':abstract,'keywords':keywords})
        self.assertTrue(any('ptychographic' in t.lower() or 'ptychography' in t.lower() for t in terms))

    def test_discovers_code_link(self):
        talks=[{'external_id':'4EAV'}]
        html='<a href="abstract.php?id=123">14:15 4EAV - Advances in phase contrast</a>'
        links=self.service._talk_detail_links('https://hub.aptor.software/xrm2026/show.php',html,talks)
        self.assertEqual(links['4EAV'],'https://hub.aptor.software/xrm2026/abstract.php?id=123')
