from .views import LoginAPIView
from django.urls import path
from .views import RegisterUserView
from .views import EditProfileView
from .views import ChangePasswordView
from .views import UploadProfilePictureView, DeleteAccountView, KYCVerificationView, GoogleAuthView
from . import views




urlpatterns = [
#Authentication endpoints
    path('login/', views.LoginAPIView.as_view(), name='login'),#POST
    path('auth/google/', GoogleAuthView.as_view(), name='google-auth'),#POST
    path('logout/', views.LogoutView.as_view(), name='logout'),#POST
    path('logout/all/', views.LogoutAllView.as_view(), name='logout-all'),#POST

    # registration endpoint
    path('register/', RegisterUserView.as_view(), name='user-register'),#POST
    path('verify-email/', views.VerifyEmailOTPView.as_view(), name='verify-email'), #POST
    path('resend-otp/', views.ResendOTPView.as_view(), name='resend-otp'), #POST
    path('forgot-password/', views.ForgotPasswordView.as_view(), name='forgot-password'), #POST
    path('reset-password/', views.ResetPasswordView.as_view(), name='reset-password'), #POST
    path('kyc-verify/', KYCVerificationView.as_view(), name='kyc-verify'), #POST
    path('subscribe/', views.InitializeSubscriptionView.as_view(), name='user-subscribe'), #POST
    path('verify-subscription/', views.VerifySubscriptionView.as_view(), name='verify-subscription'), #POST

    #update profile endpoint
    path('profile/update/', EditProfileView.as_view(), name='edit-profile'),#PUT

    #change password endpoint
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),#PUT

    # User management endpoints
    path('banks/', views.BankListView.as_view(), name='bank-list'),                 # GET
    path('profile/', views.UserProfileView.as_view(), name='profile'),              # GET
    path('profile/picture/', UploadProfilePictureView.as_view(), name='profile-picture'),  # POST (multipart)
    path('profile/delete/', DeleteAccountView.as_view(), name='delete-account'),   # DELETE

    # Support
    path('contact/', views.ContactUsView.as_view(), name='contact-us'), # POST

    # Dashboard
    path('dashboard-summary/', views.DashboardSummaryView.as_view(), name='dashboard-summary'), # GET
]


