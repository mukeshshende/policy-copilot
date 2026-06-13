"""
personas.py — Test personas for Policy Copilot
AIpportunity Pvt. Ltd.

Five personas covering all five user roles.  Each persona has:
  - name        : fictional employee name
  - role        : must match ALL_ROLES in ingest.py exactly
  - department  : for context / logging
  - queries     : 3 test questions appropriate for that role

These personas are consumed by tests/test_agent.py.
"""

from typing import TypedDict


class Persona(TypedDict):
    name:       str
    role:       str          # employee | manager | HR | IT_admin | Leadership
    department: str
    queries:    list[str]


PERSONAS: list[Persona] = [
    {
        "name":       "Priya Sharma",
        "role":       "employee",
        "department": "Engineering",
        "queries": [
            "How many days of annual leave am I entitled to?",
            "What is the work from home policy?",
            "How do I raise an IT support ticket?",
        ],
    },
    {
        "name":       "Rahul Nair",
        "role":       "manager",
        "department": "Operations",
        "queries": [
            "What is the travel expense reimbursement process?",
            "How do I approve a team member's leave request?",
            "What are the document retention requirements for project files?",
        ],
    },
    {
        "name":       "Ananya Iyer",
        "role":       "HR",
        "department": "Human Resources",
        "queries": [
            "What is the disciplinary action procedure for policy violations?",
            "How should we handle an employee termination?",
            "What are the recruitment and onboarding steps for a new hire?",
        ],
    },
    {
        "name":       "Vikram Desai",
        "role":       "IT_admin",
        "department": "Information Technology",
        "queries": [
            "What is the acceptable use policy for company devices?",
            "How should a data security incident be reported and handled?",
            "What are the software licensing compliance requirements?",
        ],
    },
    {
        "name":       "Meera Krishnan",
        "role":       "Leadership",
        "department": "Executive",
        "queries": [
            "What is the company's business continuity plan?",
            "What are the data classification and handling policies?",
            "What are the vendor management and procurement policies?",
        ],
    },
]
