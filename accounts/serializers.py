import secrets
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from content.models import Subject
from .models import SiteConfig, User


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        sid = uuid4().hex
        User.objects.filter(pk=user.pk).update(active_sid=sid)
        token["sid"] = sid
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = MeSerializer(self.user).data
        return data


class MeSerializer(serializers.ModelSerializer):
    subscription = serializers.CharField(source="subscription_state", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "role", "grade", "access_type",
                  "valid_until", "subscription", "must_change_password"]
        read_only_fields = ["id", "username", "role", "access_type", "valid_until", "subscription", "must_change_password"]

    def to_representation(self, obj):
        d = super().to_representation(obj)
        if obj.is_admin_role:
            d["role"] = "admin"
        return d


class RegisterSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    username = serializers.CharField(max_length=50)
    password = serializers.CharField(write_only=True)
    plan = serializers.ChoiceField(choices=list(settings.PLANS))

    def validate_username(self, v):
        if User.objects.filter(username__iexact=v).exists():
            raise serializers.ValidationError("Bu login band")
        return v

    def validate_password(self, v):
        validate_password(v)
        return v


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate_new_password(self, v):
        validate_password(v)
        return v


class AdminUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    generated_password = serializers.CharField(read_only=True)
    subscription = serializers.CharField(source="subscription_state", read_only=True)
    teaching_subjects = serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all(), many=True, required=False)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "role", "grade", "is_active", "access_type", "valid_until",
                  "must_change_password", "teaching_subjects", "subscription", "password", "generated_password", "date_joined"]
        read_only_fields = ["access_type", "date_joined"]

    def create(self, validated):
        subjects = validated.pop("teaching_subjects", [])
        given = validated.pop("password", "")
        pwd = given or secrets.token_urlsafe(8)
        validated.setdefault("must_change_password", SiteConfig.get().force_password_change)
        user = User(**validated, access_type=User.Access.FREE, created_by=self.context["request"].user)
        user.set_password(pwd)              # bazada faqat xesh
        user.save()
        user.teaching_subjects.set(subjects)
        user.generated_password = None if given else pwd      # avtomatik parol faqat bir marta ko'rsatiladi
        return user

    def update(self, instance, validated):
        validated.pop("password", None)
        return super().update(instance, validated)


class SiteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteConfig
        fields = ["ai_daily_limit", "force_password_change", "single_session"]
