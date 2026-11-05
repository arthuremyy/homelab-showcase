import sys, os
sys.path.insert(0, os.getcwd())
os.environ.setdefault("JWT_SECRET", "x")
from services import scoring

profile = {"xp_years": "4"}
cases = [
 ("OT PURE", {"title":"Ingénieur Cybersécurité Industrielle OT","company":"Intégrateur SI industriel",
   "description":"Sécurité des systèmes industriels, IEC 62443, SCADA, réseau industriel, automate programmable, TIA Portal. Site de production.",
   "location":"Lyon - 69","dept":"69","contract_type":"cdi","posted_at":"2026-09-05"}),
 ("CYBER EN CONTEXTE INDUSTRIEL", {"title":"Ingénieur Cybersécurité","company":"Groupe industriel",
   "description":"SOC, SIEM, analyse de vulnérabilité, ISO 27001, segmentation réseau, firewall, cloud Azure, Python. Contexte industriel multi-sites, quelques sujets OT.",
   "location":"Lyon - 69","dept":"69","contract_type":"cdi","posted_at":"2026-09-05"}),
 ("CYBER PURE", {"title":"Analyste SOC","company":"Éditeur logiciel",
   "description":"SOC, SIEM Splunk, EDR, réponse à incident, forensic, threat intelligence, Python.",
   "location":"Lyon - 69","dept":"69","contract_type":"cdi","posted_at":"2026-09-05"}),
 ("PIÈGE: AUTOMATICIEN vernis cyber", {"title":"Automaticien / Informatique industrielle","company":"PME",
   "description":"Programmation automates Siemens S7, TIA Portal, WinCC, supervision, grafcet. Notions de cybersécurité appréciées.",
   "location":"Villeurbanne - 69","dept":"69","contract_type":"cdi","posted_at":"2026-09-05"}),
 ("SENIOR 8 ANS", {"title":"Responsable Cybersécurité","company":"Adsearch",
   "description":"SOC, SIEM, ISO 27001, RSSI. Minimum 8 ans d'expérience. CISSP exigé.",
   "location":"Dardilly - 69","dept":"69","contract_type":"cdi","posted_at":"2026-08-01"}),
 ("HORS GÉO", {"title":"Ingénieur Cybersécurité","company":"ESN",
   "description":"SOC, SIEM, pentest, ISO 27001, cloud.",
   "location":"Paris 08 - 75","dept":"75","contract_type":"cdi","posted_at":"2026-09-05"}),
 ("ALTERNANCE", {"title":"Alternance Cybersécurité","company":"Groupe",
   "description":"Alternance cybersécurité SOC SIEM.",
   "location":"Lyon - 69","dept":"69","contract_type":"alternance","posted_at":"2026-09-05"}),
]
print(f"{'CAS':<34}{'TRACK':<14}{'MATCH':>6}{'PORT':>6}{'RÉUSS':>7}  LOCK")
print("-"*80)
res={}
for name, o in cases:
    s = scoring.score_offer(o, profile)
    res[name]=s
    print(f"{name:<34}{s['track']:<14}{s['match_score']:>6}{s['portability_score']:>6}"
          f"{s['success_score']:>7}  {'⚑' if s['lock_in_flag'] else ''}")
print("-"*80)
ok1 = res["CYBER EN CONTEXTE INDUSTRIEL"]["match_score"] > res["OT PURE"]["match_score"]
ok2 = res["OT PURE"]["lock_in_flag"] == 1 and res["OT PURE"]["portability_score"] < 50
ok3 = res["PIÈGE: AUTOMATICIEN vernis cyber"]["lock_in_flag"] == 1
ok4 = res["OT PURE"]["match_score"] <= scoring.OT_MATCH_CAP
print("TEST cyber_indus > ot_pur          :", "OK" if ok1 else "ÉCHEC")
print("TEST ot_pur drapeau + portabilité<50:", "OK" if ok2 else "ÉCHEC")
print("TEST piège automaticien drapeau    :", "OK" if ok3 else "ÉCHEC")
print("TEST plafond OT respecté           :", "OK" if ok4 else "ÉCHEC")
sys.exit(0 if all([ok1,ok2,ok3,ok4]) else 1)
