import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from vaultroute_rag.core.config import get_settings
from vaultroute_rag.core.security import PasswordService
from vaultroute_rag.database.session import Database
from vaultroute_rag.identity.models import Company, Department, Role, User

DEPARTMENTS = {
    "founding": "Founding",
    "engineering": "Engineering",
    "hr": "Human Resources",
    "design": "Design",
    "business": "Business",
}

ROLES = {
    "founder": ("Founder", True),
    "ceo": ("Chief Executive Officer", True),
    "director": ("Director", False),
    "cto": ("Chief Technology Officer", False),
    "engineering_manager": ("Engineering Manager", False),
    "senior_developer": ("Senior Developer", False),
    "junior_developer": ("Junior Developer", False),
    "qa_tester": ("QA Tester", False),
    "product_manager": ("Product Manager", False),
    "hr_manager": ("HR Manager", False),
    "hr_executive": ("HR Executive", False),
    "recruiter": ("Recruiter", False),
    "senior_designer": ("Senior Designer", False),
    "product_designer": ("Product Designer", False),
    "ui_ux_designer": ("UI/UX Designer", False),
    "business_manager": ("Business Manager", False),
    "sales_officer": ("Sales Officer", False),
    "business_development_executive": ("Business Development Executive", False),
    "account_manager": ("Account Manager", False),
}


@dataclass(frozen=True)
class SeedUser:
    email: str
    name: str
    role: str
    departments: tuple[str, ...]


USERS = (
    SeedUser("founder@acme.example.com", "Aarav Founder", "founder", ("founding",)),
    SeedUser("ceo@acme.example.com", "Ananya CEO", "ceo", ("founding",)),
    SeedUser("director@acme.example.com", "Dev Director", "director", ("founding",)),
    SeedUser("cto@acme.example.com", "Chirag CTO", "cto", ("founding", "engineering")),
    SeedUser(
        "engineering.manager@acme.example.com",
        "Esha Engineering Manager",
        "engineering_manager",
        ("engineering",),
    ),
    SeedUser("senior.dev@acme.example.com", "Sanjay Senior", "senior_developer", ("engineering",)),
    SeedUser("priya@acme.example.com", "Priya Junior", "junior_developer", ("engineering",)),
    SeedUser("qa@acme.example.com", "Tara Tester", "qa_tester", ("engineering",)),
    SeedUser(
        "product.manager@acme.example.com",
        "Rohan Product Manager",
        "product_manager",
        ("engineering", "design", "business"),
    ),
    SeedUser("hr.manager@acme.example.com", "Hina HR Manager", "hr_manager", ("hr",)),
    SeedUser("hr.executive@acme.example.com", "Harsh HR Executive", "hr_executive", ("hr",)),
    SeedUser("recruiter@acme.example.com", "Reena Recruiter", "recruiter", ("hr",)),
    SeedUser(
        "senior.designer@acme.example.com", "Diya Senior Designer", "senior_designer", ("design",)
    ),
    SeedUser(
        "product.designer@acme.example.com",
        "Pooja Product Designer",
        "product_designer",
        ("design",),
    ),
    SeedUser("uiux@acme.example.com", "Uma UI UX", "ui_ux_designer", ("design",)),
    SeedUser(
        "business.manager@acme.example.com",
        "Bhavya Business Manager",
        "business_manager",
        ("business",),
    ),
    SeedUser("sales@acme.example.com", "Sameer Sales", "sales_officer", ("business",)),
    SeedUser(
        "business.dev@acme.example.com",
        "Bina Business Development",
        "business_development_executive",
        ("business",),
    ),
    SeedUser(
        "account.manager@acme.example.com",
        "Akash Account Manager",
        "account_manager",
        ("business",),
    ),
)


async def seed() -> None:
    settings = get_settings()
    database = Database(settings)
    passwords = PasswordService()

    try:
        async with database.session() as session:
            company = await session.scalar(
                select(Company)
                .where(Company.slug == "acme")
                .options(
                    selectinload(Company.departments),
                    selectinload(Company.roles),
                    selectinload(Company.users).selectinload(User.roles),
                    selectinload(Company.users).selectinload(User.departments),
                )
            )
            if company is None:
                company = Company(slug="acme", name="Acme Corporation")
                session.add(company)
                await session.flush()
                department_by_code: dict[str, Department] = {}
                role_by_code: dict[str, Role] = {}
                user_by_email: dict[str, User] = {}
            else:
                department_by_code = {
                    department.code: department for department in company.departments
                }
                role_by_code = {role.code: role for role in company.roles}
                user_by_email = {user.email: user for user in company.users}

            for code, name in DEPARTMENTS.items():
                if code not in department_by_code:
                    department = Department(company_id=company.id, code=code, name=name)
                    session.add(department)
                    department_by_code[code] = department

            for code, (name, global_access) in ROLES.items():
                if code not in role_by_code:
                    role = Role(
                        company_id=company.id,
                        code=code,
                        name=name,
                        has_global_access=global_access,
                    )
                    session.add(role)
                    role_by_code[code] = role

            await session.flush()
            for seed_user in USERS:
                user = user_by_email.get(seed_user.email)
                if user is None:
                    user = User(
                        company_id=company.id,
                        email=seed_user.email,
                        full_name=seed_user.name,
                        password_hash=passwords.hash(settings.seed_user_password),
                    )
                    session.add(user)
                    user_by_email[seed_user.email] = user

                user.roles = [role_by_code[seed_user.role]]
                user.departments = [department_by_code[code] for code in seed_user.departments]

            await session.commit()
            print(
                f"Seeded company={company.slug}, departments={len(DEPARTMENTS)}, "
                f"roles={len(ROLES)}, users={len(USERS)}"
            )
            print(
                "Development password comes from SEED_USER_PASSWORD; change it outside local use."
            )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(seed())
