"""Utilities for working with Ollama models in Docker environments"""

import requests
import time
from colorama import Fore, Style
import questionary

def ensure_ollama_and_model(model_name: str, ollama_url: str) -> bool:
    """Ensure the Ollama model is available at the target Ollama endpoint."""
    print(f"{Fore.CYAN}使用 Ollama 端點：{ollama_url}{Style.RESET_ALL}")
    
    # Step 1: Check if Ollama service is available
    if not is_ollama_available(ollama_url):
        return False
        
    # Step 2: Check if model is already available
    available_models = get_available_models(ollama_url)
    if model_name in available_models:
        print(f"{Fore.GREEN}模型 {model_name} 已存在於 Docker 的 Ollama 容器中。{Style.RESET_ALL}")
        return True
        
    # Step 3: Model not available - ask if user wants to download
    print(f"{Fore.YELLOW}模型 {model_name} 目前不存在於 Docker 的 Ollama 容器中。{Style.RESET_ALL}")
    
    if not questionary.confirm(f"要下載 {model_name} 嗎？").ask():
        print(f"{Fore.RED}缺少模型，無法繼續。{Style.RESET_ALL}")
        return False
        
    # Step 4: Download the model
    return download_model(model_name, ollama_url)


def is_ollama_available(ollama_url: str) -> bool:
    """Check if Ollama service is available in Docker environment."""
    try:
        response = requests.get(f"{ollama_url}/api/version", timeout=5)
        if response.status_code == 200:
            return True
            
        print(f"{Fore.RED}無法連線至 Ollama 服務：{ollama_url}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}請確認 Docker 環境中的 Ollama 服務已啟動。{Style.RESET_ALL}")
        return False
    except requests.RequestException as e:
        print(f"{Fore.RED}連線 Ollama 服務時發生錯誤：{e}{Style.RESET_ALL}")
        return False


def get_available_models(ollama_url: str) -> list:
    """Get list of available models in Docker environment."""
    try:
        response = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return [m["name"] for m in models]
            
        print(f"{Fore.RED}取得 Ollama 可用模型失敗，狀態碼：{response.status_code}{Style.RESET_ALL}")
        return []
    except requests.RequestException as e:
        print(f"{Fore.RED}取得可用模型時發生錯誤：{e}{Style.RESET_ALL}")
        return []


def download_model(model_name: str, ollama_url: str) -> bool:
    """Download a model in Docker environment."""
    print(f"{Fore.YELLOW}正在下載模型 {model_name} 到 Docker Ollama 容器...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}此步驟可能需要一些時間，請稍候。{Style.RESET_ALL}")
    
    # Step 1: Initiate the download
    try:
        response = requests.post(f"{ollama_url}/api/pull", json={"name": model_name}, timeout=10)
        if response.status_code != 200:
            print(f"{Fore.RED}啟動模型下載失敗，狀態碼：{response.status_code}{Style.RESET_ALL}")
            if response.text:
                print(f"{Fore.RED}錯誤：{response.text}{Style.RESET_ALL}")
            return False
    except requests.RequestException as e:
        print(f"{Fore.RED}發送下載請求時發生錯誤：{e}{Style.RESET_ALL}")
        return False
    
    # Step 2: Monitor the download progress
    print(f"{Fore.CYAN}已啟動下載，將定期檢查是否完成...{Style.RESET_ALL}")
    
    total_wait_time = 0
    max_wait_time = 1800  # 30 minutes max wait
    check_interval = 10  # Check every 10 seconds
    
    while total_wait_time < max_wait_time:
        # Check if the model has been downloaded
        available_models = get_available_models(ollama_url)
        if model_name in available_models:
            print(f"{Fore.GREEN}模型 {model_name} 下載完成。{Style.RESET_ALL}")
            return True
            
        # Wait before checking again
        time.sleep(check_interval)
        total_wait_time += check_interval
        
        # Print a status message every minute
        if total_wait_time % 60 == 0:
            minutes = total_wait_time // 60
            print(f"{Fore.CYAN}下載進行中...（已經過 {minutes} 分鐘）{Style.RESET_ALL}")
    
    # If we get here, we've timed out
    print(f"{Fore.RED}等待模型下載逾時（{max_wait_time // 60} 分鐘）。{Style.RESET_ALL}")
    return False


def delete_model(model_name: str, ollama_url: str) -> bool:
    """Delete a model in Docker environment."""
    print(f"{Fore.YELLOW}正在從 Docker 容器刪除模型 {model_name}...{Style.RESET_ALL}")
    
    try:
        response = requests.delete(f"{ollama_url}/api/delete", json={"name": model_name}, timeout=10)
        if response.status_code == 200:
            print(f"{Fore.GREEN}模型 {model_name} 已成功刪除。{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}刪除模型失敗，狀態碼：{response.status_code}{Style.RESET_ALL}")
            if response.text:
                print(f"{Fore.RED}錯誤：{response.text}{Style.RESET_ALL}")
            return False
    except requests.RequestException as e:
        print(f"{Fore.RED}刪除模型時發生錯誤：{e}{Style.RESET_ALL}")
        return False 
