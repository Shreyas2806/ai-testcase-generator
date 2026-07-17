import time
import requests
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def run_test():
    manual_v1_path = Path("ct200_manual.pdf")
    manual_v2_path = Path("ct200_manual_v2.pdf")

    if not manual_v1_path.exists() or not manual_v2_path.exists():
        print("Error: Manual files not found in the root directory.")
        return

    print("=" * 70)
    print("STARTING END-TO-END VERIFICATION FLOW (WITH STALENESS)")
    print("=" * 70)

    # -------------------------------------------------------------
    # 1. Ingest Version 1
    # -------------------------------------------------------------
    print("\n[Step 1] Ingesting Version 1 (ct200_manual.pdf)...")
    url = f"{BASE_URL}/documents/upload"
    with manual_v1_path.open("rb") as f:
        files = {"file": (manual_v1_path.name, f, "application/pdf")}
        response = requests.post(url, files=files)
    
    if response.status_code != 201:
        print(f"Failed to upload v1: {response.status_code} - {response.text}")
        return

    upload_data = response.json()
    document_id = upload_data["document_id"]
    v1_number = upload_data["version"]
    print(f"Success! Document ID: {document_id}, Version: {v1_number}")

    # -------------------------------------------------------------
    # 2. Ingest Version 2
    # -------------------------------------------------------------
    print("\n[Step 2] Ingesting Version 2 (ct200_manual_v2.pdf)...")
    upload_v2_url = f"{BASE_URL}/documents/upload?document_id={document_id}"
    with manual_v2_path.open("rb") as f:
        files = {"file": (manual_v2_path.name, f, "application/pdf")}
        response = requests.post(upload_v2_url, files=files)
    
    if response.status_code != 201:
        print(f"Failed to upload v2: {response.status_code} - {response.text}")
        return

    upload_data_v2 = response.json()
    v2_number = upload_data_v2["version"]
    print(f"Success! Document ID: {document_id}, Version: {v2_number}")

    # Database Version IDs: v1 is 1, v2 is 2
    version1_db_id = 1
    version2_db_id = 2

    # -------------------------------------------------------------
    # 3. Compute Diff
    # -------------------------------------------------------------
    print("\n[Step 3] Computing Diff between Version 1 and Version 2...")
    diff_url = f"{BASE_URL}/documents/versions/{version1_db_id}/diff/{version2_db_id}"
    response = requests.post(diff_url)
    if response.status_code != 201:
        print(f"Failed to compute diff: {response.status_code} - {response.text}")
        return
    
    diff_data = response.json()
    print(f"Success! Diff Summary:")
    print(f"  Total Nodes Compared: {diff_data['total']}")
    print(f"  New: {diff_data['new']} | Changed: {diff_data['changed']} | Deleted: {diff_data['deleted']} | Unchanged: {diff_data['unchanged']}")

    # -------------------------------------------------------------
    # 4. Find a Changed Node in Version 1 to test staleness
    # -------------------------------------------------------------
    print("\n[Step 4] Finding changed nodes using the Diff API...")
    sections_url = f"{BASE_URL}/documents/{document_id}/sections?version={v1_number}"
    sections = requests.get(sections_url).json()

    changed_node_ids = []

    def find_changed_nodes(node):
        node_id = node["id"]
        # Query diff status of this node
        diff_resp = requests.get(f"{BASE_URL}/documents/diff/{node_id}")
        if diff_resp.status_code == 200:
            diff_info = diff_resp.json()
            if diff_info["changed"] and diff_info["status"] == "changed":
                print(f"  - Found changed section: '{node['heading']}' (Node ID: {node_id})")
                changed_node_ids.append(node_id)
        
        for child in node.get("children", []):
            find_changed_nodes(child)

    for sec in sections:
        find_changed_nodes(sec)

    if not changed_node_ids:
        print("Error: No changed nodes found. Cannot verify staleness.")
        return

    # Select the first changed node
    target_node_id = changed_node_ids[0]
    print(f"Target node selected for test: Node ID {target_node_id}")

    # -------------------------------------------------------------
    # 5. Create Selection containing the changed node
    # -------------------------------------------------------------
    print("\n[Step 5] Creating a Named Selection on Version 1 containing the changed node...")
    selection_url = f"{BASE_URL}/selections"
    selection_payload = {
        "version_id": version1_db_id,
        "name": "General Specs Suite",
        "description": "Checks details that will change in v2.",
        "node_ids": [target_node_id]
    }
    response = requests.post(selection_url, json=selection_payload)
    if response.status_code != 201:
        print(f"Failed to create selection: {response.status_code} - {response.text}")
        return
    
    selection_data = response.json()
    selection_id = selection_data["id"]
    print(f"Success! Selection ID: {selection_id} created.")

    # -------------------------------------------------------------
    # 6. Generate AI Test Cases on Version 1 Selection
    # -------------------------------------------------------------
    print("\n[Step 6] Generating AI Test Cases from Gemini for Version 1 Selection...")
    gen_url = f"{BASE_URL}/selections/{selection_id}/generate-tests"
    response = requests.post(gen_url)
    if response.status_code != 201:
        print(f"Failed to generate tests: {response.status_code} - {response.text}")
        return
    
    gen_data = response.json()
    test_run_id = gen_data["result_id"]
    print(f"Success! Generated Test Run ID: {test_run_id}")
    print("\nGenerated Test Cases:")
    for idx, tc in enumerate(gen_data["test_cases"][:2]): # print first two for brevity
        print(f"\nTest {idx+1}: {tc['title']} [Priority: {tc['priority']}]")
        print(f"  Objective: {tc['objective']}")
        print(f"  Expected: {tc['expected_result']}")

    # -------------------------------------------------------------
    # 7. Check Test Run Staleness against Version 2
    # -------------------------------------------------------------
    print("\n[Step 7] Checking Staleness for the Test Run relative to Version 2...")
    status_url = f"{BASE_URL}/tests/{test_run_id}/status"
    response = requests.get(status_url)
    if response.status_code != 200:
        print(f"Failed to check staleness: {response.status_code} - {response.text}")
        return
    
    stale_data = response.json()
    print(f"\nStaleness Status: {stale_data['status']}")
    if stale_data["status"] == "STALE":
        print("\nStale Details (Affected sections that changed or were deleted in Version 2):")
        for node in stale_data.get("changed_nodes", []):
            print(f"  - Node {node['node_id']} '{node['heading']}' was {node['reason']}")
            # Fetch detailed diff
            node_diff = requests.get(f"{BASE_URL}/documents/diff/{node['node_id']}").json()
            print(f"    Change Summary: {node_diff['summary']}")

    print("\n" + "=" * 70)
    print("END-TO-END VERIFICATION COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_test()
