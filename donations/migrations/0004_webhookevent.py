from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('donations', '0003_articlepurchase_marathon_marathonpurchase_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='WebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=50, verbose_name='Провайдер')),
                ('event_id', models.CharField(max_length=255, verbose_name='ID события')),
                ('payload_hash', models.CharField(max_length=64, verbose_name='SHA256 payload')),
                ('processed', models.BooleanField(default=False, verbose_name='Обработано')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('processed_at', models.DateTimeField(blank=True, null=True, verbose_name='Обработано в')),
                ('donation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='webhook_events', to='donations.donation', verbose_name='Связанный донат')),
            ],
            options={
                'verbose_name': 'Webhook событие',
                'verbose_name_plural': 'Webhook события',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='webhookevent',
            constraint=models.UniqueConstraint(fields=('provider', 'event_id'), name='uq_webhook_provider_event'),
        ),
        migrations.AddIndex(
            model_name='webhookevent',
            index=models.Index(fields=['provider', 'event_id'], name='donations_w_provider_77e77d_idx'),
        ),
        migrations.AddIndex(
            model_name='webhookevent',
            index=models.Index(fields=['processed', '-created_at'], name='donations_w_processe_ce03f4_idx'),
        ),
    ]
