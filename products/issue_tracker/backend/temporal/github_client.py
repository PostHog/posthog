"""
GitHub API client utilities for issue tracker workflows.
"""
import asyncio
import aiohttp
from typing import Dict, Any, Optional
from urllib.parse import urljoin

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


class GitHubClient:
    """Async GitHub API client for issue tracker operations."""
    
    def __init__(self, token: str, repo_owner: str, repo_name: str):
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PostHog-IssueTracker/1.0"
        }
    
    async def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main"
    ) -> Dict[str, Any]:
        """
        Create a pull request.
        
        Args:
            title: PR title
            body: PR description/body
            head_branch: Source branch (the branch with changes)
            base_branch: Target branch (usually main/master)
            
        Returns:
            Dict with PR information including URL, number, etc.
        """
        url = f"{self.base_url}/repos/{self.repo_owner}/{self.repo_name}/pulls"
        
        data = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.headers, json=data) as response:
                    if response.status == 201:
                        pr_data = await response.json()
                        logger.info(f"Created PR #{pr_data['number']}: {pr_data['html_url']}")
                        return {
                            "success": True,
                            "pr_number": pr_data["number"],
                            "pr_url": pr_data["html_url"],
                            "pr_id": pr_data["id"],
                            "data": pr_data
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to create PR: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"GitHub API error: {response.status} - {error_text}",
                            "status_code": response.status
                        }
                        
        except Exception as e:
            logger.error(f"Error creating pull request: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to create pull request: {str(e)}"
            }
    
    async def get_repository_info(self) -> Dict[str, Any]:
        """
        Get repository information and validate access.
        
        Returns:
            Dict with repository info or error details
        """
        url = f"{self.base_url}/repos/{self.repo_owner}/{self.repo_name}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        repo_data = await response.json()
                        logger.info(f"Repository access validated: {repo_data['full_name']}")
                        return {
                            "success": True,
                            "repo_name": repo_data["name"],
                            "repo_full_name": repo_data["full_name"],
                            "default_branch": repo_data["default_branch"],
                            "clone_url": repo_data["clone_url"],
                            "html_url": repo_data["html_url"],
                            "private": repo_data["private"],
                            "data": repo_data
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to access repository: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"Cannot access repository: {response.status} - {error_text}",
                            "status_code": response.status
                        }
                        
        except Exception as e:
            logger.error(f"Error getting repository info: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to get repository info: {str(e)}"
            }
    
    async def check_branch_exists(self, branch_name: str) -> Dict[str, Any]:
        """
        Check if a branch exists in the repository.
        
        Args:
            branch_name: Name of the branch to check
            
        Returns:
            Dict with exists status and branch info
        """
        url = f"{self.base_url}/repos/{self.repo_owner}/{self.repo_name}/branches/{branch_name}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        branch_data = await response.json()
                        return {
                            "success": True,
                            "exists": True,
                            "branch_name": branch_data["name"],
                            "commit_sha": branch_data["commit"]["sha"],
                            "data": branch_data
                        }
                    elif response.status == 404:
                        return {
                            "success": True,
                            "exists": False,
                            "branch_name": branch_name
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Error checking branch: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"GitHub API error: {response.status} - {error_text}",
                            "status_code": response.status
                        }
                        
        except Exception as e:
            logger.error(f"Error checking branch existence: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to check branch: {str(e)}"
            }
    
    async def get_file_content(self, file_path: str, branch: str = None) -> Dict[str, Any]:
        """
        Get the content of a file from the repository.
        
        Args:
            file_path: Path to the file in the repository
            branch: Branch name (optional, defaults to default branch)
            
        Returns:
            Dict with file content and metadata
        """
        url = f"{self.base_url}/repos/{self.repo_owner}/{self.repo_name}/contents/{file_path}"
        params = {}
        if branch:
            params["ref"] = branch
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        file_data = await response.json()
                        
                        # Decode base64 content if it's a file
                        if file_data.get("type") == "file" and "content" in file_data:
                            import base64
                            content = base64.b64decode(file_data["content"]).decode('utf-8')
                            file_data["decoded_content"] = content
                        
                        return {
                            "success": True,
                            "file_path": file_path,
                            "content": file_data.get("decoded_content", ""),
                            "sha": file_data.get("sha"),
                            "size": file_data.get("size"),
                            "data": file_data
                        }
                    elif response.status == 404:
                        return {
                            "success": False,
                            "error": f"File not found: {file_path}",
                            "status_code": 404
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Error getting file content: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"GitHub API error: {response.status} - {error_text}",
                            "status_code": response.status
                        }
                        
        except Exception as e:
            logger.error(f"Error getting file content: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to get file content: {str(e)}"
            }