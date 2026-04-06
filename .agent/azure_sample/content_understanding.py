import os
from azure.ai.contentunderstanding import ContentUnderstandingClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
load_dotenv()

# 1. 配置你的资源信息
endpoint = os.getenv("AZURE_CONTENT_UNDER_ENDPOINT")
key # : https://<your-resource-name>.cognitiveservices.azure.com/
key = os.getenv("AZURE_CONTENT_UNDER_API_KEY")
identifier = os.getenv("AZURE_CONTENT_UNDERSTANDING_PREBUILT_IDENTIFIER")
file_path = "path/to/your/local_file.pdf"


def analyze_local_pdf(endpoint, key, pdf_path):
    # 2. 初始化客户端
    client = ContentUnderstandingClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    # 3. 读取本地 PDF 文件为字节流
    with open(pdf_path, "rb") as f:
        file_content = f.read()

    print(f"正在分析文件: {pdf_path}...")

    # 4. 调用 prebuilt-documentSearch 模型
    # analyzer_id 为 "prebuilt-documentSearch"
    poller = client.begin_analyze_binary(
        analyzer_id=identifier,
        binary_input=file_content,
        content_type="application/pdf"
    )

    # 5. 等待分析结果
    result = poller.result()

    # 6. 处理结果 (例如打印提取的 Markdown 内容)
    print("\n--- 分析完成 ---\n")
    for content in result.contents:
        if content.markdown:
            print("提取的 Markdown 内容摘要:")
            print(content.markdown[:1000])  # 打印前 1000 个字符
        
        # 如果需要处理具体字段 (Fields)
        if content.fields:
            print("\n提取的字段:")
            for field_name, field_value in content.fields.items():
                print(f"- {field_name}: {field_value.value if field_value else 'N/A'}")

if __name__ == "__main__":
    # 请确保替换为实际的 endpoint, key 和文件路径
    # analyze_local_pdf(endpoint, key, file_path)
    pass