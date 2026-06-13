# data/policies — Synthetic Policy Documents

This directory contains 26 synthetic policy documents for AIpportunity Pvt. Ltd., used as the knowledge base for Policy Copilot.

All documents are fictional and created solely for demonstration purposes. They are chunked and embedded into ChromaDB during ingestion.

---

## Structure

```
data/policies/
├── hr/      # 9 documents — Human Resources policies
├── ops/     # 9 documents — Operations policies
└── it/      # 8 documents — IT policies
```

---

## HR Policies (`hr/`)

| File | Description | Sensitivity |
|---|---|---|
| `hr-code-of-conduct-v1.txt` | Workplace behaviour, ethics, disciplinary action | internal |
| `hr-compensation-grades-v1.txt` | Salary bands and grade structure | restricted |
| `hr-employee-wellness-v1.txt` | Mental health, EAP, wellness programmes | internal |
| `hr-grievance-redressal-v1.txt` | Grievance filing and resolution process | internal |
| `hr-learning-development-v1.txt` | Training, certifications, learning budgets | internal |
| `hr-leave-policy-v1.txt` | Annual, sick, maternity/paternity leave entitlements | internal |
| `hr-performance-management-v1.txt` | PIP, appraisal cycles, rating framework | internal |
| `hr-posh-policy-v1.txt` | Prevention of sexual harassment (PoSH) | confidential |
| `hr-recruitment-onboarding-v1.txt` | Hiring process, offer letters, onboarding steps | internal |

---

## Operations Policies (`ops/`)

| File | Description | Sensitivity |
|---|---|---|
| `ops-asset-management-v1.txt` | Company asset tracking and disposal | internal |
| `ops-business-continuity-v1.txt` | BCP, DR procedures, RTO/RPO targets | confidential |
| `ops-document-retention-v1.txt` | Document lifecycle, retention periods, archival | internal |
| `ops-health-safety-v1.txt` | Workplace safety, emergency procedures | internal |
| `ops-meeting-comms-v1.txt` | Meeting etiquette, communication standards | internal |
| `ops-procurement-authority-v1.txt` | Purchase approval thresholds by role | restricted |
| `ops-remote-work-hybrid-v1.txt` | WFH eligibility, hybrid work guidelines | internal |
| `ops-travel-expense-v1.txt` | Travel booking, expense claims, reimbursement limits | internal |
| `ops-vendor-onboarding-v1.txt` | Vendor evaluation, contract, onboarding process | internal |

---

## IT Policies (`it/`)

| File | Description | Sensitivity |
|---|---|---|
| `it-acceptable-use-v1.txt` | Company device and internet usage rules | internal |
| `it-ai-tools-acceptable-use-v1.txt` | Approved AI tools, data handling with AI | internal |
| `it-byod-v1.txt` | Bring Your Own Device policy and MDM requirements | internal |
| `it-cloud-saas-usage-v1.txt` | Approved cloud services, shadow IT rules | internal |
| `it-incident-response-v1.txt` | Security incident classification and response steps | confidential |
| `it-password-access-v1.txt` | Password standards, MFA, access provisioning | internal |
| `it-remote-access-vpn-v1.txt` | VPN usage, remote access controls | internal |
| `it-software-license-v1.txt` | Software procurement, licence compliance | internal |

---

## Sensitivity Levels

| Level | Meaning | Example |
|---|---|---|
| `internal` | Accessible to all employees by default | Leave policy, WFH guidelines |
| `restricted` | Limited to specific roles (HR, Leadership) | Salary bands, procurement authority |
| `confidential` | Sensitive — HR and Leadership only | PoSH policy, BCP, incident response |

---

## Audience Flags

Each document chunk is tagged with five boolean flags at ingestion time:

| Flag | Role |
|---|---|
| `audience_employee` | employee |
| `audience_manager` | manager |
| `audience_HR` | HR |
| `audience_IT_admin` | IT_admin |
| `audience_Leadership` | Leadership |

ChromaDB retrieval applies `where={f"audience_{user_role}": True}` — a chunk is never returned to a role that is not explicitly flagged.

---

## Re-ingesting

If you add or modify documents, re-run the ingestion pipeline:

```bash
cd ~/policy-copilot
source .venv/bin/activate
python -m src.ingestion.ingest
```

This clears and rebuilds all three ChromaDB collections (`hr_policies`, `ops_policies`, `it_policies`).
