from django.test import TestCase


class CreditsTests(TestCase):
    def test_footer_credits_the_developer_without_donation_link(self):
        page = self.client.get("/")
        self.assertContains(page, 'href="https://vincent.foriel.pro/fr/"')
        self.assertContains(page, "avec l'aide de Claude")
        self.assertNotContains(page, "github.com/sponsors")
        english = self.client.get("/en/")
        self.assertContains(english, 'href="https://vincent.foriel.pro/en/"')
        self.assertContains(english, "with the help of Claude")
