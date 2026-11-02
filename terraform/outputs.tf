output "public_ip" {
  value = aws_instance.app.public_ip
}

output "url" {
  value = "https://${aws_instance.app.public_ip}/"
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/id_ed25519 ubuntu@${aws_instance.app.public_ip}"
}
