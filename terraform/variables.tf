variable "region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "my_ip" {
  type        = string
  description = "Your public IP in CIDR form, for example 1.2.3.4/32"
}

variable "public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "repo_url" {
  type    = string
  default = "https://github.com/Ahmadyousaf57/prod-stack.git"
}
