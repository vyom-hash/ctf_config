"""
Standalone script to verify OpenStack connection and flavor fetching.
Run using:
    python test_openstack_connection.py
"""
from openstack_client.connection import Connection
from openstack.exceptions import SDKException
from app.core.config import settings

def test_openstack_connection():
    print("Attempting to connect to OpenStack...")

    try:
        conn = Connection(
            auth_url=settings.OPENSTACK_AUTH_URL,
            username=settings.OPENSTACK_USERNAME,
            password=settings.OPENSTACK_PASSWORD,
            user_domain_name=settings.OPENSTACK_USER_DOMAIN_NAME,
            project_domain_name=settings.OPENSTACK_PROJECT_DOMAIN_NAME,
            region_name=settings.OPENSTACK_REGION_NAME,
        )

        # Step 1: Authenticate
        conn.authorize()
        print("Authentication successful.")

        # Step 2: Fetch flavors
        flavors = list(conn.compute.flavors())

        print(f"Successfully fetched {len(flavors)} flavors.\n")

        for flavor in flavors:
            print(
                f"Name: {flavor.name} | "
                f"VCPUs: {flavor.vcpus} | "
                f"RAM: {flavor.ram} MB | "
                f"Disk: {flavor.disk} GB"
            )

    except SDKException as e:
        print("OpenStack SDK Error:")
        print(str(e))

    except Exception as e:
        print("Unexpected Error:")
        print(str(e))


if __name__ == "__main__":
    test_openstack_connection()