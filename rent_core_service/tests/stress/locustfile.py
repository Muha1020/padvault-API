from locust import HttpUser, task, between

class PadvaultTenantUser(HttpUser):
    # Simulate a wait time between 1 and 3 seconds between actions
    wait_time = between(1, 3)

    @task(3)
    def view_properties(self):
        """Simulate a user browsing the public properties list."""
        self.client.get("/api/properties/")

    @task(1)
    def search_properties(self):
        """Simulate a user searching for a specific property."""
        self.client.get("/api/properties/search/?q=Lagos")

    @task(1)
    def view_categories(self):
        """Simulate a user checking property categories."""
        self.client.get("/api/properties/categories/")

    @task(2)
    def view_featured_properties(self):
        """Simulate a user checking the featured properties."""
        self.client.get("/api/properties/featured/")
