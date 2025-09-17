from django.core.management.base import BaseCommand
from posthog.models import Team
from products.tasks.backend.models import AgentDefinition


class Command(BaseCommand):
    help = "Create default agent definitions for all teams"

    def handle(self, *args, **options):
        agents_created = 0
        
        for team in Team.objects.all():
            default_agents = [
                {
                    'name': 'Code Generation Agent',
                    'agent_type': AgentDefinition.AgentType.CODE_GENERATION,
                    'description': 'Generates code changes based on task requirements',
                    'config': {
                        'max_files_per_task': 10,
                        'supported_languages': ['python', 'typescript', 'javascript'],
                        'code_style': 'posthog'
                    }
                },
                {
                    'name': 'Triage Agent',
                    'agent_type': AgentDefinition.AgentType.TRIAGE,
                    'description': 'Analyzes and categorizes incoming tasks',
                    'config': {
                        'auto_assign_priority': True,
                        'auto_assign_tags': True
                    }
                },
                {
                    'name': 'Review Agent',
                    'agent_type': AgentDefinition.AgentType.REVIEW,
                    'description': 'Reviews completed work for quality and compliance',
                    'config': {
                        'check_tests': True,
                        'check_docs': True,
                        'check_security': True
                    }
                },
                {
                    'name': 'Testing Agent',
                    'agent_type': AgentDefinition.AgentType.TESTING,
                    'description': 'Runs automated tests and validates functionality',
                    'config': {
                        'run_unit_tests': True,
                        'run_integration_tests': True,
                        'generate_test_reports': True
                    }
                }
            ]
            
            for agent_data in default_agents:
                agent, created = AgentDefinition.objects.get_or_create(
                    team=team,
                    name=agent_data['name'],
                    defaults=agent_data
                )
                if created:
                    agents_created += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"Created agent '{agent.name}' for team {team.name}")
                    )
        
        self.stdout.write(
            self.style.SUCCESS(f"Successfully created {agents_created} default agents")
        )