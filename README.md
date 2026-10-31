# Flask 3-Tier on AWS: Practice Guide

Region in examples: eu-west-2 (London). Swap for your own.

## 0. Test locally
    docker compose up
Open http://localhost:8080, add notes, refresh. Push this folder to a public GitHub repo.

## 1. VPC (10.0.0.0/16) with 9 subnets across 3 AZs
| Tier    | AZ a         | AZ b         | AZ c         |
|---------|--------------|--------------|--------------|
| Public  | 10.0.1.0/24  | 10.0.2.0/24  | 10.0.3.0/24  |
| Private | 10.0.11.0/24 | 10.0.12.0/24 | 10.0.13.0/24 |
| Data    | 10.0.21.0/24 | 10.0.22.0/24 | 10.0.23.0/24 |

- Internet Gateway attached to the VPC. Public route table: 0.0.0.0/0 -> IGW.
- One NAT Gateway in a public subnet. Private route table: 0.0.0.0/0 -> NAT.
- Data route table: local only (no internet route).
Tip: the VPC console "VPC and more" wizard builds most of this.

## 2. Security groups (chain them, reference by SG ID)
| SG       | Inbound                      |
|----------|------------------------------|
| alb-sg   | 80 from 0.0.0.0/0            |
| app-sg   | 8080 from alb-sg             |
| db-sg    | 5432 from app-sg             |
| cache-sg | 6379 from app-sg             |

## 3. Data tier
- RDS PostgreSQL, db.t3.micro (free tier), DB subnet group = 3 data subnets,
  SG db-sg, initial DB name `notesdb`, public access No.
  Later practice: enable Multi-AZ and watch failover.
- ElastiCache Redis OSS, cache.t3.micro, subnet group = data subnets,
  SG cache-sg, encryption in transit OFF (the app connects without TLS).
Copy both endpoints.

## 4. App tier
1. Edit user_data.sh with your repo URL and endpoints.
2. Launch Template: Amazon Linux 2023, t3.micro, app-sg, no public IP,
   paste user_data.sh into User data.
3. Target Group: HTTP 8080, health check path `/health`.
4. Auto Scaling Group: 3 private subnets, attach target group,
   ELB health checks ON, desired 3 / min 2 / max 6,
   target tracking policy: CPU 50%.

## 5. Presentation tier
- Application Load Balancer, internet-facing, 3 public subnets, alb-sg,
  listener HTTP:80 -> target group.
- Optional: Route 53 alias record for your domain -> ALB.

## 6. Experiments (the point of the exercise)
1. Refresh the ALB URL. Instance and AZ change, visit count holds (Redis sessions).
2. Watch "Notes source" flip between RDS and ElastiCache.
3. Terminate an instance. ASG replaces it, users see no error.
4. Load test (`ab -n 20000 -c 100 http://ALB/`) and watch the ASG scale out.
5. Try to reach an EC2 or RDS directly from the internet. It fails, by design.
6. Use Session Manager (attach AmazonSSMManagedInstanceCore role) to get a shell, no SSH or bastion needed.

## 7. Cost and cleanup
Roughly $2-3 per day if left running. NAT Gateway (~$1.10/day) and ALB (~$0.60/day)
are not free tier. Delete in this order: ASG, ALB, target group, RDS,
ElastiCache, NAT Gateway, release Elastic IP, VPC.
